"""Flask Web UI for the SVG Icon Agent."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, jsonify, request, send_from_directory, url_for

from svg_icon_agent.backends import create_openrouter_client
from svg_icon_agent.exporter import export_artifacts
from svg_icon_agent.llm_agents import (
    CandidateCritique,
    LlmCritiqueResult,
    LlmSelectionResult,
    OpenRouterSvgOptimizerAgent,
)
from svg_icon_agent.models import IconPlan, SvgArtifact
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL, OpenRouterClient
from svg_icon_agent.openrouter_client import OpenRouterError, OpenRouterResponse
from svg_icon_agent.pipeline import EventProgressLogger, make_reasoning_config, run_single_prompt_pipeline
from svg_icon_agent.prompts import PromptItem, make_prompt_from_text
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.svg_check_tool import SvgCheckTool

RUN_ID_RE = re.compile(r"^[a-z0-9-]+$")
ClientFactory = Callable[[str, float, int], OpenRouterClient]


@dataclass
class WebRun:
    id: str
    prompt: str
    model: str
    output_dir: Path
    max_refine_rounds: int
    request_timeout: float
    max_retries: int
    empty_response_retries: int
    max_tokens: int | None
    reasoning_effort: str | None
    reasoning_max_tokens: int | None
    workflow: str
    candidate_count: int
    rewrite_prompt: bool
    optimizer_feedback: str | None
    use_llm_optimizer_feedback: bool
    status: str = "queued"
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    prompt_rewrites: dict[str, dict[str, str]] = field(default_factory=dict)
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def create_app(
    *,
    output_root: Path | str = Path("outputs/web"),
    client_factory: ClientFactory | None = None,
    run_async: bool = True,
) -> Flask:
    app = Flask(__name__)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    runs: dict[str, WebRun] = {}
    lock = threading.Lock()

    @app.get("/")
    def index() -> Response:
        return Response(_INDEX_HTML, mimetype="text/html")

    @app.post("/api/runs")
    def create_run() -> Response:
        payload = request.get_json(silent=True) or {}
        prompt = str(payload.get("prompt") or "").strip()
        if len(prompt) < 3:
            return jsonify({"error": "Prompt must contain at least 3 characters."}), 400

        model = str(payload.get("model") or DEFAULT_OPENROUTER_MODEL).strip() or DEFAULT_OPENROUTER_MODEL
        max_refine_rounds = _int_value(payload.get("max_refine_rounds"), 3, minimum=0, maximum=8)
        request_timeout = _float_value(payload.get("request_timeout"), 60.0, minimum=5.0, maximum=300.0)
        max_retries = _int_value(payload.get("max_retries"), 2, minimum=0, maximum=5)
        empty_response_retries = _int_value(payload.get("empty_response_retries"), 3, minimum=0, maximum=10)
        max_tokens = _optional_int_value(payload.get("max_tokens"), minimum=256, maximum=20000)
        reasoning_effort = _reasoning_effort_value(payload.get("reasoning_effort"))
        reasoning_max_tokens = _optional_int_value(payload.get("reasoning_max_tokens"), minimum=0, maximum=20000)
        workflow = _workflow_value(payload.get("workflow"))
        candidate_count = _int_value(payload.get("candidate_count"), 3, minimum=1, maximum=6)
        rewrite_prompt = bool(payload.get("rewrite_prompt", True))
        optimizer_feedback = _optional_text_value(payload.get("optimizer_feedback"))
        use_llm_optimizer_feedback = bool(payload.get("use_llm_optimizer_feedback", True))
        run_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        run = WebRun(
            id=run_id,
            prompt=prompt,
            model=model,
            output_dir=root / run_id,
            max_refine_rounds=max_refine_rounds,
            request_timeout=request_timeout,
            max_retries=max_retries,
            empty_response_retries=empty_response_retries,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            reasoning_max_tokens=reasoning_max_tokens,
            workflow=workflow,
            candidate_count=candidate_count,
            rewrite_prompt=rewrite_prompt,
            optimizer_feedback=optimizer_feedback,
            use_llm_optimizer_feedback=use_llm_optimizer_feedback,
        )
        with lock:
            runs[run_id] = run

        if run_async:
            thread = threading.Thread(target=_execute_run, args=(run, client_factory), daemon=True)
            thread.start()
        else:
            _execute_run(run, client_factory)
        return jsonify(_run_payload(run))

    @app.get("/api/runs")
    def list_runs() -> Response:
        with lock:
            recent = sorted(runs.values(), key=lambda item: item.created_at, reverse=True)[:20]
        return jsonify({"runs": [_run_payload(run, include_files=False) for run in recent]})

    @app.get("/api/runs/<run_id>")
    def get_run(run_id: str) -> Response:
        if not _valid_run_id(run_id):
            return jsonify({"error": "Invalid run id."}), 404
        with lock:
            run = runs.get(run_id)
        if run is None:
            output_dir = root / run_id
            if not output_dir.exists():
                return jsonify({"error": "Run not found."}), 404
            run = WebRun(
                id=run_id,
                prompt="",
                model="",
                output_dir=output_dir,
                max_refine_rounds=0,
                request_timeout=0,
                max_retries=0,
                empty_response_retries=3,
                max_tokens=None,
                reasoning_effort=None,
                reasoning_max_tokens=None,
                workflow="collaborative",
                candidate_count=3,
                rewrite_prompt=True,
                optimizer_feedback=None,
                use_llm_optimizer_feedback=True,
            )
            run.status = "completed" if (output_dir / "metrics.json").exists() else "failed"
        return jsonify(_run_payload(run))

    @app.post("/api/runs/<run_id>/optimize")
    def optimize_run(run_id: str) -> Response:
        if not _valid_run_id(run_id):
            return jsonify({"error": "Invalid run id."}), 404
        payload = request.get_json(silent=True) or {}
        feedback = _optional_text_value(payload.get("optimizer_feedback"))
        if not feedback:
            return jsonify({"error": "Optimizer feedback must contain at least one instruction."}), 400
        use_llm_feedback = bool(payload.get("use_llm_optimizer_feedback", True))
        with lock:
            run = runs.get(run_id)
        if run is None:
            return jsonify({"error": "Run is not loaded in this Web session."}), 404
        if run.status in {"queued", "running", "optimizing"}:
            return jsonify({"error": "Run is still busy."}), 409
        if not run.output_dir.exists():
            return jsonify({"error": "Run output directory is missing."}), 404

        run.status = "optimizing"
        run.error = None
        run.optimizer_feedback = feedback
        run.use_llm_optimizer_feedback = use_llm_feedback
        run.updated_at = time.time()
        run.events.append(
            {
                "elapsed": 0.0,
                "message": "Starting post-run manual SVG optimization.",
                "stage": "optimizer",
            }
        )

        if run_async:
            thread = threading.Thread(
                target=_execute_post_run_optimization,
                args=(run, client_factory, feedback, use_llm_feedback),
                daemon=True,
            )
            thread.start()
        else:
            _execute_post_run_optimization(run, client_factory, feedback, use_llm_feedback)
        return jsonify(_run_payload(run))

    @app.get("/outputs/<run_id>/<path:filename>")
    def web_outputs(run_id: str, filename: str):
        if not _valid_run_id(run_id):
            return jsonify({"error": "Invalid run id."}), 404
        output_dir = root / run_id
        if not output_dir.exists():
            return jsonify({"error": "Run not found."}), 404
        return send_from_directory(output_dir, filename)

    return app


def _execute_run(run: WebRun, client_factory: ClientFactory | None) -> None:
    run.status = "running"
    run.updated_at = time.time()
    logger = EventProgressLogger(verbose=False, events=run.events, prompt_rewrites=run.prompt_rewrites)
    prompt_item = make_prompt_from_text(run.prompt, source="web")
    try:
        client = client_factory(run.model, run.request_timeout, run.max_retries) if client_factory else None
        result = run_single_prompt_pipeline(
            prompt_item,
            output_dir=run.output_dir,
            model=run.model,
            max_refine_rounds=run.max_refine_rounds,
            request_timeout=run.request_timeout,
            max_retries=run.max_retries,
            empty_response_retries=run.empty_response_retries,
            max_tokens=run.max_tokens,
            reasoning_effort=run.reasoning_effort,
            reasoning_max_tokens=run.reasoning_max_tokens,
            workflow=run.workflow,
            candidate_count=run.candidate_count,
            rewrite_prompt=run.rewrite_prompt,
            optimizer_feedback=run.optimizer_feedback,
            use_llm_optimizer_feedback=run.use_llm_optimizer_feedback,
            client=client,
            progress=logger,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary for UI threads.
        run.status = "failed"
        run.error = str(exc)
        run.events.append({"elapsed": round(logger.elapsed_seconds(), 1), "message": f"Web run failed: {exc}", "stage": "error"})
    else:
        run.status = result.status
        run.error = result.error
        run.raw_events = result.raw_events
        run.summary = dict(result.summary)
    run.updated_at = time.time()


def _execute_post_run_optimization(
    run: WebRun,
    client_factory: ClientFactory | None,
    feedback: str,
    use_llm_feedback: bool,
) -> None:
    logger = EventProgressLogger(verbose=False, events=run.events, prompt_rewrites=run.prompt_rewrites)
    try:
        client = _make_web_client(run, client_factory)
        _post_run_optimize(
            run,
            feedback=feedback,
            use_llm_feedback=use_llm_feedback,
            client=client,
            logger=logger,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary for UI threads.
        run.status = "failed"
        run.error = str(exc)
        run.events.append(
            {
                "elapsed": round(logger.elapsed_seconds(), 1),
                "message": f"Post-run optimization failed: {exc}",
                "stage": "error",
            }
        )
    else:
        run.status = "completed"
        run.error = None
        run.raw_events = _read_jsonl(run.output_dir / "llm_raw_responses.jsonl")
        run.summary = _read_json(run.output_dir / "metrics.json") or {}
    run.updated_at = time.time()


def _post_run_optimize(
    run: WebRun,
    *,
    feedback: str,
    use_llm_feedback: bool,
    client: OpenRouterClient,
    logger: EventProgressLogger,
) -> None:
    plan = _load_run_plan(run.output_dir)
    source_artifact = _load_post_run_source_artifact(run.output_dir, plan.id)
    source_backup_dir = run.output_dir / "post_run_sources"
    source_backup_dir.mkdir(parents=True, exist_ok=True)
    source_backup = source_backup_dir / f"{plan.id}-{int(time.time())}.svg"
    source_backup.write_text(source_artifact.svg, encoding="utf-8")

    trace_rows = _read_json(run.output_dir / "llm_trace.json")
    trace_item = trace_rows[0] if isinstance(trace_rows, list) and trace_rows and isinstance(trace_rows[0], dict) else {}
    critiques = _critiques_from_trace(trace_item, run.model)
    selection = _selection_from_trace(trace_item, run.model)
    tool_report = SvgCheckTool().check(source_artifact)
    reasoning = make_reasoning_config(run.reasoning_effort, run.reasoning_max_tokens)
    optimizer = OpenRouterSvgOptimizerAgent(client, max_tokens=run.max_tokens, reasoning=reasoning)

    raw_events = _read_jsonl(run.output_dir / "llm_raw_responses.jsonl")
    logger.log(f"{plan.id}: requesting post-run SVG optimizer.")
    try:
        optimized = optimizer.optimize(
            plan,
            source_artifact,
            critiques,
            tool_report,
            selection,
            manual_feedback=feedback,
            use_llm_feedback=use_llm_feedback,
        )
    except OpenRouterError as exc:
        raw_events.append(
            {
                "id": plan.id,
                "stage": "post-run-optimizer",
                "status": "error",
                "model": run.model,
                "error": str(exc),
                "debug_payload": exc.debug_payload,
                "manual_feedback": feedback,
                "use_llm_feedback": use_llm_feedback,
            }
        )
        _write_jsonl(run.output_dir / "llm_raw_responses.jsonl", raw_events)
        _update_post_run_trace(
            run.output_dir,
            optimizer_status="openrouter-error",
            feedback=feedback,
            use_llm_feedback=use_llm_feedback,
            feedback_sources=[],
            usage=None,
            error=str(exc),
        )
        raise

    raw_events.append(
        {
            "id": plan.id,
            "stage": "post-run-optimizer",
            "status": "success",
            "model": run.model,
            "response": optimized.response.raw,
            "manual_feedback": feedback,
            "use_llm_feedback": use_llm_feedback,
            "feedback_sources": list(optimized.feedback_sources),
        }
    )
    baseline_dir = run.output_dir / "baseline"
    refined_dir = run.output_dir / "refined"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / f"{plan.id}.svg").write_text(optimized.artifact.svg, encoding="utf-8")

    logger.log(f"{plan.id}: validating post-run optimized SVG.")
    refinements = refine_artifacts(
        [plan],
        [optimized.artifact],
        client=client,
        max_rounds=run.max_refine_rounds,
        model=run.model,
        max_tokens=run.max_tokens,
        reasoning=reasoning,
        collaboration_briefs={plan.id: f"Post-run manual optimizer feedback: {feedback}"},
        progress=logger,
    )
    refined_artifacts = [result.artifact for result in refinements]
    baseline_reports = [result.baseline_report for result in refinements]
    refined_reports = [result.refined_report for result in refinements]
    for artifact in refined_artifacts:
        (refined_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")
    for result in refinements:
        raw_events.extend(result.raw_llm_events)

    _write_run_json_reports(run.output_dir, baseline_reports, refined_reports, refinements)
    _write_jsonl(run.output_dir / "llm_raw_responses.jsonl", raw_events)
    prompt_item = PromptItem(
        id=plan.id,
        category=plan.category,
        prompt=plan.prompt,
        style=plan.style,
        palette=plan.palette,
        source="web-post-run",
    )
    summary = export_artifacts(
        output_dir=run.output_dir,
        prompts=[prompt_item],
        baseline_artifacts=[optimized.artifact],
        refined_artifacts=refined_artifacts,
        baseline_reports=baseline_reports,
        refined_reports=refined_reports,
        refinements=refinements,
    )
    run.summary = dict(summary)
    refinement = refinements[0] if refinements else None
    _update_post_run_trace(
        run.output_dir,
        optimizer_status="openrouter",
        feedback=feedback,
        use_llm_feedback=use_llm_feedback,
        feedback_sources=list(optimized.feedback_sources),
        usage=optimized.response.usage,
        baseline_score=baseline_reports[0].score if baseline_reports else None,
        baseline_valid=baseline_reports[0].is_valid if baseline_reports else None,
        refined_score=refined_reports[0].score if refined_reports else None,
        refined_valid=refined_reports[0].is_valid if refined_reports else None,
        score_delta=refined_reports[0].score - baseline_reports[0].score if baseline_reports and refined_reports else None,
        validator_backend=refinement.agent_statuses.get("validator") if refinement else None,
        refiner_backend=refinement.agent_statuses.get("refiner") if refinement else None,
    )
    logger.log(f"{plan.id}: post-run manual optimization complete.")


def _make_web_client(run: WebRun, client_factory: ClientFactory | None) -> OpenRouterClient:
    if client_factory:
        return client_factory(run.model, run.request_timeout, run.max_retries)
    return create_openrouter_client(
        model=run.model,
        request_timeout=run.request_timeout,
        max_retries=run.max_retries,
        empty_response_retries=run.empty_response_retries,
    )


def _run_payload(run: WebRun, *, include_files: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": run.id,
        "prompt": run.prompt,
        "model": run.model,
        "max_tokens": run.max_tokens,
        "empty_response_retries": run.empty_response_retries,
        "reasoning_effort": run.reasoning_effort,
        "reasoning_max_tokens": run.reasoning_max_tokens,
        "workflow": run.workflow,
        "candidate_count": run.candidate_count,
        "rewrite_prompt": run.rewrite_prompt,
        "optimizer_feedback": run.optimizer_feedback,
        "use_llm_optimizer_feedback": run.use_llm_optimizer_feedback,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "events": list(run.events),
        "prompt_rewrite": _prompt_rewrite_payload(run),
        "summary": _read_json(run.output_dir / "metrics.json") or run.summary,
        "trace": _read_json(run.output_dir / "llm_trace.json"),
        "baseline_validation": _read_json(run.output_dir / "baseline_validation.json"),
        "refined_validation": _read_json(run.output_dir / "refined_validation.json"),
        "raw_events": _read_jsonl(run.output_dir / "llm_raw_responses.jsonl") or run.raw_events,
    }
    if include_files:
        payload["artifacts"] = _artifact_payload(run)
    return payload


def _prompt_rewrite_payload(run: WebRun) -> dict[str, str] | None:
    if run.prompt_rewrites:
        return next(iter(run.prompt_rewrites.values()))
    trace = _read_json(run.output_dir / "llm_trace.json")
    if isinstance(trace, list) and trace:
        first = trace[0]
        if isinstance(first, dict):
            original = first.get("original_prompt")
            rewritten = first.get("rewritten_prompt")
            if isinstance(original, str) or isinstance(rewritten, str):
                return {
                    "original_prompt": original if isinstance(original, str) else "",
                    "rewritten_prompt": rewritten if isinstance(rewritten, str) else "",
                }
    if run.prompt:
        return {"original_prompt": run.prompt, "rewritten_prompt": ""}
    return None


def _artifact_payload(run: WebRun) -> dict[str, Any]:
    artifact_id = _first_svg_id(run.output_dir / "refined") or _first_svg_id(run.output_dir / "baseline")
    if not artifact_id:
        return {}
    files = {
        "selected_svg": Path("selected") / f"{artifact_id}.svg",
        "baseline_svg": Path("baseline") / f"{artifact_id}.svg",
        "refined_svg": Path("refined") / f"{artifact_id}.svg",
        "baseline_png": Path("png/baseline") / f"{artifact_id}.png",
        "refined_png": Path("png/refined") / f"{artifact_id}.png",
        "gallery": Path("gallery.html"),
    }
    artifacts: dict[str, Any] = {"id": artifact_id}
    for key, relative in files.items():
        path = run.output_dir / relative
        if path.exists():
            artifacts[f"{key}_url"] = _versioned_output_url(run, relative, path)
    selected_svg = run.output_dir / files["selected_svg"]
    baseline_svg = run.output_dir / files["baseline_svg"]
    refined_svg = run.output_dir / files["refined_svg"]
    if selected_svg.exists():
        artifacts["selected_svg_text"] = selected_svg.read_text(encoding="utf-8")
    if baseline_svg.exists():
        artifacts["baseline_svg_text"] = baseline_svg.read_text(encoding="utf-8")
    if refined_svg.exists():
        artifacts["refined_svg_text"] = refined_svg.read_text(encoding="utf-8")
    candidate_dir = run.output_dir / "candidates"
    candidates = []
    for path in sorted(candidate_dir.glob(f"{artifact_id}-candidate-*.svg")):
        relative = Path("candidates") / path.name
        candidate = {
            "id": path.stem.replace(f"{artifact_id}-", ""),
            "svg_text": path.read_text(encoding="utf-8"),
            "svg_url": _versioned_output_url(run, relative, path),
        }
        candidates.append(candidate)
    if candidates:
        artifacts["candidates"] = candidates
    return artifacts


def _versioned_output_url(run: WebRun, relative: Path, path: Path) -> str:
    return url_for("web_outputs", run_id=run.id, filename=str(relative), v=path.stat().st_mtime_ns)


def _load_run_plan(output_dir: Path) -> IconPlan:
    data = _read_json(output_dir / "plans.json")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("Run does not contain a reusable icon plan.")
    item = data[0]
    return IconPlan(
        id=str(item.get("id") or ""),
        category=str(item.get("category") or "object"),
        prompt=str(item.get("prompt") or ""),
        style=str(item.get("style") or "mixed"),
        palette=_tuple3(item.get("palette"), ("#2563eb", "#dbeafe", "#111827")),
        motifs=tuple(str(value) for value in item.get("motifs") or ()),
        layout=str(item.get("layout") or "post-run"),
        constraints=tuple(str(value) for value in item.get("constraints") or ()),
    )


def _load_post_run_source_artifact(output_dir: Path, artifact_id: str) -> SvgArtifact:
    for stage in ("refined", "baseline", "selected"):
        path = output_dir / stage / f"{artifact_id}.svg"
        if path.exists():
            return SvgArtifact(id=artifact_id, stage="post-run-source", svg=path.read_text(encoding="utf-8"))
    raise ValueError("Run does not contain an SVG artifact to optimize.")


def _critiques_from_trace(trace_item: dict[str, Any], model: str) -> list[LlmCritiqueResult]:
    reports = trace_item.get("critic_reports")
    if not isinstance(reports, dict):
        return []
    results: list[LlmCritiqueResult] = []
    for perspective, by_candidate in reports.items():
        if not isinstance(by_candidate, dict):
            continue
        critiques: list[CandidateCritique] = []
        for candidate_id, data in by_candidate.items():
            if not isinstance(data, dict):
                continue
            critiques.append(
                CandidateCritique(
                    candidate_id=str(candidate_id),
                    score=_int_value(data.get("score"), 0, minimum=0, maximum=100),
                    strengths=_text_tuple(data.get("strengths")),
                    issues=_text_tuple(data.get("issues")),
                    recommendation=str(data.get("recommendation") or "No recommendation provided."),
                )
            )
        if critiques:
            results.append(
                LlmCritiqueResult(
                    perspective=str(perspective),
                    critiques=tuple(critiques),
                    response=OpenRouterResponse(content="{}", model=model),
                )
            )
    return results


def _selection_from_trace(trace_item: dict[str, Any], model: str) -> LlmSelectionResult:
    winner = trace_item.get("selected_candidate_id")
    rationale = trace_item.get("selector_rationale")
    repair_brief = trace_item.get("selector_repair_brief")
    risks = trace_item.get("selector_risks")
    return LlmSelectionResult(
        winner_candidate_id=str(winner or "post-run-source"),
        rationale=str(rationale or "Post-run optimization starts from the latest generated SVG."),
        risks=_text_tuple(risks),
        repair_brief=str(repair_brief or "Apply the user's post-run feedback while preserving the icon intent."),
        response=OpenRouterResponse(content="{}", model=model),
    )


def _write_run_json_reports(output_dir: Path, baseline_reports, refined_reports, refinements) -> None:
    (output_dir / "baseline_validation.json").write_text(
        json.dumps([report.to_json() for report in baseline_reports], indent=2),
        encoding="utf-8",
    )
    (output_dir / "refined_validation.json").write_text(
        json.dumps([report.to_json() for report in refined_reports], indent=2),
        encoding="utf-8",
    )
    (output_dir / "refinement_history.json").write_text(
        json.dumps([result.to_json() for result in refinements], indent=2),
        encoding="utf-8",
    )


def _update_post_run_trace(
    output_dir: Path,
    *,
    optimizer_status: str,
    feedback: str,
    use_llm_feedback: bool,
    feedback_sources: list[str],
    usage: dict[str, Any] | None,
    error: str | None = None,
    baseline_score: int | None = None,
    baseline_valid: bool | None = None,
    refined_score: int | None = None,
    refined_valid: bool | None = None,
    score_delta: int | None = None,
    validator_backend: str | None = None,
    refiner_backend: str | None = None,
) -> None:
    path = output_dir / "llm_trace.json"
    rows = _read_json(path)
    if not isinstance(rows, list) or not rows:
        rows = [{"id": _first_svg_id(output_dir / "baseline") or "manual"}]
    item = rows[0] if isinstance(rows[0], dict) else {}
    count = _int_value(item.get("post_run_optimizer_count"), 0, minimum=0, maximum=999) + 1
    item["post_run_optimizer_count"] = count
    item["post_run_optimizer_backend"] = optimizer_status
    item["post_run_optimizer_applied"] = optimizer_status == "openrouter"
    item["post_run_optimizer_feedback"] = feedback
    item["post_run_use_llm_feedback"] = use_llm_feedback
    item["post_run_optimizer_feedback_sources"] = feedback_sources
    if usage is not None:
        usage_map = item.get("usage")
        if not isinstance(usage_map, dict):
            usage_map = {}
        usage_map[f"post_run_optimizer_{count}"] = usage
        item["usage"] = usage_map
    if error:
        errors = item.get("errors")
        if not isinstance(errors, list):
            errors = []
        errors.append(f"post-run-optimizer: {error}")
        item["errors"] = errors
    if baseline_score is not None:
        item["baseline_score"] = baseline_score
    if baseline_valid is not None:
        item["baseline_valid"] = baseline_valid
    if refined_score is not None:
        item["refined_score"] = refined_score
    if refined_valid is not None:
        item["refined_valid"] = refined_valid
    if score_delta is not None:
        item["score_delta"] = score_delta
    if validator_backend:
        item["validator_backend"] = validator_backend
    if refiner_backend:
        item["refiner_backend"] = refiner_backend
    rows[0] = item
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _first_svg_id(directory: Path) -> str | None:
    if not directory.exists():
        return None
    for path in sorted(directory.glob("*.svg")):
        return path.stem
    return None


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _valid_run_id(run_id: str) -> bool:
    return bool(RUN_ID_RE.match(run_id))


def _int_value(value: Any, fallback: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _float_value(value: Any, fallback: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _optional_int_value(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _optional_text_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _tuple3(value: Any, fallback: tuple[str, str, str]) -> tuple[str, str, str]:
    if isinstance(value, list) and len(value) == 3:
        return (str(value[0]), str(value[1]), str(value[2]))
    return fallback


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item.strip())


def _reasoning_effort_value(value: Any) -> str | None:
    effort = str(value or "none").strip().lower()
    if effort in {"", "default"}:
        return None
    if effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        return "none"
    return effort


def _workflow_value(value: Any) -> str:
    workflow = str(value or "collaborative").strip().lower()
    if workflow not in {"collaborative", "single"}:
        return "collaborative"
    return workflow


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SVG Icon Agent</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #667085;
      --line: #d8dee9;
      --accent: #1570ef;
      --ok: #079455;
      --warn: #b54708;
      --bad: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    main {
      width: min(1440px, 100%);
      margin: 0 auto;
      padding: 18px;
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 16px;
    }
    section, aside {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside {
      min-height: calc(100vh - 36px);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 22px; line-height: 1.2; }
    h2 { font-size: 16px; }
    h3 { font-size: 14px; }
    label {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }
    textarea, input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font: inherit;
      color: var(--ink);
      background: #fff;
    }
    input[type="checkbox"] {
      width: auto;
      margin-right: 8px;
    }
    textarea {
      min-height: 132px;
      resize: vertical;
      line-height: 1.45;
    }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .button-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    button {
      height: 40px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .status {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font-size: 13px;
      color: var(--muted);
    }
    .workspace {
      display: grid;
      grid-template-rows: auto minmax(360px, 1fr) auto minmax(260px, 42vh);
      gap: 16px;
    }
    .topbar {
      padding: 14px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .prompt-panel {
      padding: 14px 16px;
      display: grid;
      gap: 10px;
    }
    .prompt-compare {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .prompt-box {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-height: 82px;
      background: #fbfdff;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.45;
    }
    .optimizer-summary {
      border-top: 1px solid var(--line);
      padding-top: 10px;
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .previews {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      padding: 16px;
    }
    .candidates {
      padding: 16px;
      display: grid;
      gap: 12px;
    }
    .candidate-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    figure {
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 320px;
      display: grid;
      grid-template-rows: 36px minmax(0, 1fr) auto;
      background: #fbfdff;
      overflow: hidden;
    }
    figcaption {
      padding: 10px 12px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
    }
    .figure-title {
      padding: 9px 12px;
      border-bottom: 1px solid var(--line);
      font-weight: 700;
      font-size: 13px;
    }
    .candidate-meta {
      border-top: 1px solid var(--line);
      padding: 10px 12px;
      display: grid;
      gap: 8px;
      background: #ffffff;
      font-size: 12px;
      color: var(--muted);
    }
    .score-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .score-chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 7px;
      color: var(--ink);
      background: #f8fafc;
      font-weight: 700;
    }
    .critic-note {
      border-left: 3px solid var(--line);
      padding-left: 8px;
      line-height: 1.35;
    }
    .preview-box {
      min-height: 0;
      display: grid;
      place-items: center;
      padding: 16px;
      background:
        linear-gradient(45deg, #eef2f7 25%, transparent 25%),
        linear-gradient(-45deg, #eef2f7 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #eef2f7 75%),
        linear-gradient(-45deg, transparent 75%, #eef2f7 75%);
      background-size: 22px 22px;
      background-position: 0 0, 0 11px, 11px -11px, -11px 0;
    }
    .preview-box img, .svg-preview svg {
      width: min(100%, 300px);
      height: auto;
      max-height: 300px;
      background: white;
      border-radius: 6px;
    }
    .tabs {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      border-bottom: 1px solid var(--line);
    }
    .tab {
      height: 38px;
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
      background: #fff;
      color: var(--muted);
    }
    .tab.active {
      color: var(--ink);
      background: #eef6ff;
    }
    .log-panel {
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .log-body {
      overflow: auto;
      padding: 12px;
    }
    .timeline {
      display: grid;
      gap: 8px;
    }
    .event {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      display: grid;
      grid-template-columns: 76px 116px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      font-size: 13px;
    }
    .stage {
      color: var(--accent);
      font-weight: 700;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.45;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .empty {
      color: var(--muted);
      display: grid;
      place-items: center;
      min-height: 180px;
      text-align: center;
      padding: 20px;
    }
    .ok { color: var(--ok); }
    .bad { color: var(--bad); }
    .warn { color: var(--warn); }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      aside { min-height: auto; }
      .previews { grid-template-columns: 1fr; }
      .candidate-grid { grid-template-columns: 1fr; }
      .prompt-compare { grid-template-columns: 1fr; }
      .event { grid-template-columns: 64px 92px minmax(0, 1fr); }
    }
  </style>
</head>
<body>
  <main>
    <aside>
      <h1>SVG Icon Agent</h1>
      <div>
        <label for="prompt">Description</label>
        <textarea id="prompt">a minimal rocket launch icon with a dynamic flame</textarea>
      </div>
      <div>
        <label for="model">Model</label>
        <input id="model" value="__MODEL__">
      </div>
      <div class="row">
        <div>
          <label for="workflow">Workflow</label>
          <select id="workflow">
            <option value="collaborative" selected>collaborative</option>
            <option value="single">single</option>
          </select>
        </div>
        <div>
          <label for="candidateCount">Candidates</label>
          <input id="candidateCount" type="number" min="1" max="6" value="3">
        </div>
      </div>
      <label>
        <input id="rewritePrompt" type="checkbox" checked>
        Prompt Rewriter Agent
      </label>
      <label>
        <input id="useLlmOptimizerFeedback" type="checkbox" checked>
        Use LLM feedback
      </label>
      <div>
        <label for="optimizerFeedback">Optimizer feedback</label>
        <textarea id="optimizerFeedback" style="min-height: 86px" placeholder="Optional manual improvement advice"></textarea>
      </div>
      <div class="row">
        <div>
          <label for="rounds">Repair rounds</label>
          <input id="rounds" type="number" min="0" max="8" value="3">
        </div>
        <div>
          <label for="timeout">Timeout</label>
          <input id="timeout" type="number" min="5" max="300" value="60">
        </div>
      </div>
      <div>
        <label for="emptyRetries">Empty retries</label>
        <input id="emptyRetries" type="number" min="0" max="10" value="3">
      </div>
      <div>
        <label for="maxTokens">Max tokens</label>
        <input id="maxTokens" type="number" min="256" max="20000" value="4096">
      </div>
      <div class="row">
        <div>
          <label for="reasoningEffort">Reasoning effort</label>
          <select id="reasoningEffort">
            <option value="none" selected>none</option>
            <option value="minimal">minimal</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="xhigh">xhigh</option>
          </select>
        </div>
        <div>
          <label for="reasoningTokens">Reasoning tokens</label>
          <input id="reasoningTokens" type="number" min="0" max="20000" placeholder="optional">
        </div>
      </div>
      <div class="button-row">
        <button id="runButton" type="button">Run</button>
        <button id="optimizeButton" type="button" disabled>Apply feedback</button>
      </div>
      <div id="status" class="status">Idle</div>
    </aside>
    <div class="workspace">
      <section class="topbar">
        <h2>Run Output</h2>
        <div>
          <span id="runId" class="pill">No run</span>
          <span id="runState" class="pill">idle</span>
        </div>
        <div id="optimizerSummary" class="optimizer-summary">Waiting for SVG Optimizer Agent context</div>
      </section>
      <section class="prompt-panel">
        <h2>Prompt Rewrite</h2>
        <div class="prompt-compare">
          <div>
            <label>Original</label>
            <div id="originalPrompt" class="prompt-box">Waiting for input</div>
          </div>
          <div>
            <label>Rewritten</label>
            <div id="rewrittenPrompt" class="prompt-box">Waiting for Prompt Rewriter Agent</div>
          </div>
        </div>
      </section>
      <section class="previews">
        <figure>
          <div class="figure-title">Selected SVG</div>
          <div id="selectedSvg" class="preview-box svg-preview"><div class="empty">No selected SVG</div></div>
          <figcaption id="selectedCaption">Waiting for Consensus Selector Agent</figcaption>
        </figure>
        <figure>
          <div class="figure-title">Optimized Baseline SVG</div>
          <div id="baselineSvg" class="preview-box svg-preview"><div class="empty">No baseline SVG</div></div>
          <figcaption id="baselineCaption">Waiting for SVG Optimizer Agent</figcaption>
        </figure>
        <figure>
          <div class="figure-title">Refined PNG</div>
          <div id="refinedPng" class="preview-box"><div class="empty">No refined PNG</div></div>
          <figcaption id="refinedCaption">Waiting for Validator and Refiner Agents</figcaption>
        </figure>
      </section>
      <section class="candidates">
        <h2>Candidate Drafts</h2>
        <div id="candidateGrid" class="candidate-grid"><div class="empty">No candidates yet</div></div>
      </section>
      <section class="log-panel">
        <div class="tabs">
          <button class="tab active" data-tab="timeline" type="button">Flow</button>
          <button class="tab" data-tab="trace" type="button">Trace</button>
          <button class="tab" data-tab="raw" type="button">Raw LLM</button>
        </div>
        <div id="timeline" class="log-body"></div>
        <div id="trace" class="log-body" hidden></div>
        <div id="raw" class="log-body" hidden></div>
      </section>
    </div>
  </main>
  <script>
    const state = { runId: null, timer: null, activeTab: 'timeline' };
    const runButton = document.getElementById('runButton');
    const optimizeButton = document.getElementById('optimizeButton');
    const statusBox = document.getElementById('status');
    const runIdBox = document.getElementById('runId');
    const runStateBox = document.getElementById('runState');

    document.querySelectorAll('.tab').forEach((button) => {
      button.addEventListener('click', () => {
        state.activeTab = button.dataset.tab;
        document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab === button));
        ['timeline', 'trace', 'raw'].forEach((id) => {
          document.getElementById(id).hidden = id !== state.activeTab;
        });
      });
    });

    runButton.addEventListener('click', async () => {
      const payload = {
        prompt: document.getElementById('prompt').value,
        model: document.getElementById('model').value,
        max_refine_rounds: Number(document.getElementById('rounds').value),
        workflow: document.getElementById('workflow').value,
        candidate_count: Number(document.getElementById('candidateCount').value),
        rewrite_prompt: document.getElementById('rewritePrompt').checked,
        request_timeout: Number(document.getElementById('timeout').value),
        empty_response_retries: Number(document.getElementById('emptyRetries').value),
        max_tokens: Number(document.getElementById('maxTokens').value) || null,
        reasoning_effort: document.getElementById('reasoningEffort').value,
        reasoning_max_tokens: Number(document.getElementById('reasoningTokens').value) || null,
        optimizer_feedback: document.getElementById('optimizerFeedback').value,
        use_llm_optimizer_feedback: document.getElementById('useLlmOptimizerFeedback').checked
      };
      runButton.disabled = true;
      setStatus('Submitting run...', '');
      clearInterval(state.timer);
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        runButton.disabled = false;
        setStatus(data.error || 'Run could not start.', 'bad');
        return;
      }
      state.runId = data.id;
      renderRun(data);
      state.timer = setInterval(() => pollRun(), 1200);
    });

    optimizeButton.addEventListener('click', async () => {
      if (!state.runId) {
        setStatus('Run an icon pipeline first.', 'bad');
        return;
      }
      const feedback = document.getElementById('optimizerFeedback').value.trim();
      if (!feedback) {
        setStatus('Enter optimizer feedback first.', 'bad');
        return;
      }
      const payload = {
        optimizer_feedback: feedback,
        use_llm_optimizer_feedback: document.getElementById('useLlmOptimizerFeedback').checked
      };
      runButton.disabled = true;
      optimizeButton.disabled = true;
      setStatus('Submitting post-run optimization...', '');
      clearInterval(state.timer);
      const response = await fetch(`/api/runs/${state.runId}/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.error || 'Post-run optimization could not start.', 'bad');
        runButton.disabled = false;
        optimizeButton.disabled = false;
        return;
      }
      renderRun(data);
      state.timer = setInterval(() => pollRun(), 1200);
    });

    async function pollRun() {
      if (!state.runId) return;
      const response = await fetch(`/api/runs/${state.runId}`);
      const data = await response.json();
      renderRun(data);
      if (data.status === 'completed' || data.status === 'failed') {
        clearInterval(state.timer);
        runButton.disabled = false;
      }
    }

    function renderRun(data) {
      runIdBox.textContent = data.id || 'No run';
      runStateBox.textContent = data.status || 'unknown';
      runStateBox.className = `pill ${data.status === 'completed' ? 'ok' : data.status === 'failed' ? 'bad' : ''}`;
      setStatus(data.error || statusText(data), data.status === 'failed' ? 'bad' : data.status === 'completed' ? 'ok' : '');
      renderTimeline(data.events || []);
      renderJson('trace', data.trace || data.summary || {});
      renderJson('raw', data.raw_events || []);
      renderPromptRewrite(data);
      renderOptimizerContext(data);
      renderArtifacts(data.artifacts || {});
      renderCandidates((data.artifacts || {}).candidates || [], data.trace || []);
      syncButtons(data);
    }

    function statusText(data) {
      if (data.status === 'completed') return 'Completed';
      if (data.status === 'optimizing') return 'Optimizing from manual feedback';
      if (data.status === 'running') return 'Running';
      if (data.status === 'queued') return 'Queued';
      return 'Idle';
    }

    function setStatus(text, cls) {
      statusBox.textContent = text;
      statusBox.className = `status ${cls || ''}`;
    }

    function syncButtons(data) {
      const busy = ['queued', 'running', 'optimizing'].includes(data.status);
      runButton.disabled = busy;
      optimizeButton.disabled = busy || !data.id || !(data.artifacts && (data.artifacts.refined_svg_text || data.artifacts.baseline_svg_text));
    }

    function renderTimeline(events) {
      const box = document.getElementById('timeline');
      if (!events.length) {
        box.innerHTML = '<div class="empty">No flow events</div>';
        return;
      }
      box.innerHTML = `<div class="timeline">${events.map((event) => `
        <div class="event">
          <span>${Number(event.elapsed || 0).toFixed(1)}s</span>
          <span class="stage">${escapeHtml(event.stage || 'pipeline')}</span>
          <span>${escapeHtml(event.message || '')}</span>
        </div>
      `).join('')}</div>`;
    }

    function renderJson(id, value) {
      const box = document.getElementById(id);
      box.innerHTML = `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
    }

    function renderArtifacts(artifacts) {
      const selected = document.getElementById('selectedSvg');
      const baseline = document.getElementById('baselineSvg');
      const refined = document.getElementById('refinedPng');
      document.getElementById('selectedCaption').textContent = artifacts.selected_svg_url || 'Waiting for Consensus Selector Agent';
      document.getElementById('baselineCaption').textContent = artifacts.baseline_svg_url || 'Waiting for SVG Optimizer Agent';
      document.getElementById('refinedCaption').textContent = artifacts.refined_png_url || 'Waiting for Refiner Agent';
      selected.innerHTML = artifacts.selected_svg_text ? artifacts.selected_svg_text : '<div class="empty">No selected SVG</div>';
      baseline.innerHTML = artifacts.baseline_svg_text ? artifacts.baseline_svg_text : '<div class="empty">No baseline SVG</div>';
      refined.innerHTML = artifacts.refined_png_url ? `<img src="${artifacts.refined_png_url}" alt="Refined PNG">` : '<div class="empty">No refined PNG</div>';
    }

    function renderPromptRewrite(data) {
      const traceItem = data.trace && data.trace[0] ? data.trace[0] : {};
      const liveRewrite = data.prompt_rewrite || {};
      document.getElementById('originalPrompt').textContent =
        liveRewrite.original_prompt || traceItem.original_prompt || data.prompt || 'Waiting for input';
      document.getElementById('rewrittenPrompt').textContent =
        liveRewrite.rewritten_prompt || traceItem.rewritten_prompt || 'Waiting for Prompt Rewriter Agent';
    }

    function renderOptimizerContext(data) {
      const traceItem = data.trace && data.trace[0] ? data.trace[0] : {};
      const manual = traceItem.post_run_optimizer_feedback || traceItem.manual_optimizer_feedback || data.optimizer_feedback || 'none';
      const useLlm = traceItem.post_run_use_llm_feedback !== undefined
        ? traceItem.post_run_use_llm_feedback
        : traceItem.use_llm_optimizer_feedback !== undefined
          ? traceItem.use_llm_optimizer_feedback
          : data.use_llm_optimizer_feedback;
      const traceSources = Array.isArray(traceItem.post_run_optimizer_feedback_sources) && traceItem.post_run_optimizer_feedback_sources.length
        ? traceItem.post_run_optimizer_feedback_sources
        : traceItem.optimizer_feedback_sources;
      const sources = Array.isArray(traceSources) && traceSources.length
        ? traceSources.join(', ')
        : 'waiting';
      document.getElementById('optimizerSummary').innerHTML = `
        <div><strong>Manual feedback:</strong> ${escapeHtml(manual)}</div>
        <div><strong>Use LLM feedback:</strong> ${escapeHtml(useLlm)}</div>
        <div><strong>Feedback sources:</strong> ${escapeHtml(sources)}</div>
      `;
    }

    function renderCandidates(candidates, trace) {
      const grid = document.getElementById('candidateGrid');
      if (!candidates.length) {
        grid.innerHTML = '<div class="empty">No candidates yet</div>';
        return;
      }
      const winner = trace && trace[0] ? trace[0].selected_candidate_id : null;
      const traceItem = trace && trace[0] ? trace[0] : {};
      grid.innerHTML = candidates.map((candidate) => `
        <figure>
          <div class="figure-title">${escapeHtml(candidate.id)}${candidate.id === winner ? ' selected' : ''}</div>
          <div class="preview-box svg-preview">${candidate.svg_text || '<div class="empty">No SVG</div>'}</div>
          ${renderCandidateMeta(candidate.id, traceItem)}
        </figure>
      `).join('');
    }

    function renderCandidateMeta(candidateId, traceItem) {
      const toolScore = traceItem.candidate_tool_scores ? traceItem.candidate_tool_scores[candidateId] : undefined;
      const semantic = traceItem.critic_reports && traceItem.critic_reports.semantic
        ? traceItem.critic_reports.semantic[candidateId]
        : null;
      const quality = traceItem.critic_reports && traceItem.critic_reports['svg-quality']
        ? traceItem.critic_reports['svg-quality'][candidateId]
        : null;
      return `
        <div class="candidate-meta">
          <div class="score-row">
            ${scoreChip('Tool', toolScore)}
            ${scoreChip('Semantic', semantic && semantic.score)}
            ${scoreChip('SVG quality', quality && quality.score)}
          </div>
          ${criticNote('Semantic', semantic)}
          ${criticNote('SVG quality', quality)}
        </div>
      `;
    }

    function scoreChip(label, score) {
      return `<span class="score-chip">${escapeHtml(label)} ${score === undefined || score === null ? '-' : escapeHtml(score)}</span>`;
    }

    function criticNote(label, report) {
      if (!report) return `<div class="critic-note">${escapeHtml(label)}: waiting for critique</div>`;
      const strengths = Array.isArray(report.strengths) && report.strengths.length ? report.strengths.join('; ') : 'no strengths listed';
      const issues = Array.isArray(report.issues) && report.issues.length ? report.issues.join('; ') : 'no issues listed';
      return `
        <div class="critic-note">
          <strong>${escapeHtml(label)}</strong><br>
          Strengths: ${escapeHtml(strengths)}<br>
          Issues: ${escapeHtml(issues)}<br>
          Recommendation: ${escapeHtml(report.recommendation || 'none')}
        </div>
      `;
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[char]));
    }
  </script>
</body>
</html>""".replace("__MODEL__", DEFAULT_OPENROUTER_MODEL)
