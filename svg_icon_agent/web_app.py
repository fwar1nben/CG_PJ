"""Flask Web UI for the SVG Icon Agent."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, jsonify, request, send_from_directory, url_for

from svg_icon_agent.backends import create_openrouter_client
from svg_icon_agent.exporter import export_artifacts, render_svg_to_png
from svg_icon_agent.llm_agents import (
    CandidateCritique,
    LlmCritiqueResult,
    LlmSelectionResult,
    SvgOptimizerAgent,
)
from svg_icon_agent.memory import MemoryContext, MemoryRecord, RetrievedMemory
from svg_icon_agent.models import GenerationGoal, IconPlan, SvgArtifact
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL, OpenRouterClient
from svg_icon_agent.openrouter_client import OpenRouterError, OpenRouterResponse
from svg_icon_agent.pipeline import EventProgressLogger, make_reasoning_config, run_single_prompt_pipeline
from svg_icon_agent.prompts import PromptItem, make_prompt_from_text
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.svg_check_tool import SvgCheckTool

RUN_ID_RE = re.compile(r"^[a-z0-9-]+$")
ClientFactory = Callable[[str, float, int], OpenRouterClient]

WORKFLOW_NODES: tuple[dict[str, str], ...] = (
    {"id": "memory", "label": "Memory"},
    {"id": "goal-manager", "label": "Goal"},
    {"id": "prompt-rewriter", "label": "Rewriter"},
    {"id": "planner", "label": "Planner"},
    {"id": "svg-generator", "label": "Generator / Candidates"},
    {"id": "critic", "label": "Critics"},
    {"id": "selector", "label": "Selector"},
    {"id": "optimizer", "label": "Optimizer"},
    {"id": "validator", "label": "Validator"},
    {"id": "failure-taxonomy", "label": "Failure Taxonomy"},
    {"id": "repair-router", "label": "Repair Router"},
    {"id": "refiner", "label": "Refiner"},
    {"id": "memory-curator", "label": "Curator"},
    {"id": "exporter", "label": "Exporter"},
)

STAGE_TO_NODE = {
    "memory": "memory",
    "goal-manager": "goal-manager",
    "prompt-rewriter": "prompt-rewriter",
    "planner": "planner",
    "svg-generator": "svg-generator",
    "candidate-generator": "svg-generator",
    "candidate-svg": "svg-generator",
    "critic": "critic",
    "semantic-critic": "critic",
    "svg-quality-critic": "critic",
    "selector": "selector",
    "optimizer": "optimizer",
    "svg-optimizer": "optimizer",
    "post-run-optimizer": "optimizer",
    "validator": "validator",
    "failure-taxonomy": "failure-taxonomy",
    "repair-router": "repair-router",
    "refiner": "refiner",
    "memory-curator": "memory-curator",
    "exporter": "exporter",
}


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
    manual_goal: str | None
    memory_enabled: bool
    memory_top_k: int
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
        default_model = os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
        return Response(_INDEX_HTML.replace("__MODEL__", default_model), mimetype="text/html")

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
        manual_goal = _optional_text_value(payload.get("goal"))
        memory_enabled = bool(payload.get("memory_enabled", True))
        memory_top_k = _int_value(payload.get("memory_top_k"), 3, minimum=0, maximum=10)
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
            manual_goal=manual_goal,
            memory_enabled=memory_enabled,
            memory_top_k=memory_top_k,
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
                manual_goal=None,
                memory_enabled=True,
                memory_top_k=3,
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

    @app.post("/api/runs/<run_id>/edited-svg")
    def save_edited_svg(run_id: str) -> Response:
        if not _valid_run_id(run_id):
            return jsonify({"error": "Invalid run id."}), 404
        payload = request.get_json(silent=True) or {}
        svg = str(payload.get("svg") or "").strip()
        source = str(payload.get("source") or "refined").strip().lower()
        if not svg:
            return jsonify({"error": "Edited SVG must not be empty."}), 400
        if source not in {"refined", "baseline", "selected"}:
            return jsonify({"error": "Edited SVG source must be refined, baseline, or selected."}), 400
        with lock:
            run = runs.get(run_id)
        if run is None:
            return jsonify({"error": "Run is not loaded in this Web session."}), 404
        if run.status in {"queued", "running", "optimizing"}:
            return jsonify({"error": "Run is still busy."}), 409
        if not run.output_dir.exists():
            return jsonify({"error": "Run output directory is missing."}), 404

        try:
            _save_edited_svg(run, svg=svg, source=source)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pragma: no cover - defensive boundary for rendering failures.
            return jsonify({"error": f"Edited SVG could not be saved: {exc}"}), 400

        run.updated_at = time.time()
        run.events.append(
            {
                "elapsed": 0.0,
                "message": f"Saved edited SVG from {source}.",
                "stage": "editor",
            }
        )
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
            manual_goal=run.manual_goal,
            memory_enabled=run.memory_enabled,
            memory_top_k=run.memory_top_k,
            memory_index_path=_memory_root_for_run(run) / "memory" / "memory_index.jsonl",
            memory_outputs_root=_memory_root_for_run(run),
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
    goal = _load_run_goal(run.output_dir, plan.id)
    memory_context = _load_run_memory_context(run.output_dir, plan.id)
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
    optimizer = SvgOptimizerAgent(client, max_tokens=run.max_tokens, reasoning=reasoning)

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
            goal=goal,
            memory_context=memory_context,
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
        failure_taxonomy_backend=refinement.agent_statuses.get("failure_taxonomy") if refinement else None,
        repair_router_backend=refinement.agent_statuses.get("repair_router") if refinement else None,
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


def _memory_root_for_run(run: WebRun) -> Path:
    output_root = run.output_dir.parent
    if output_root.name == "web":
        return output_root.parent
    return output_root


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
        "goal": run.manual_goal,
        "memory_enabled": run.memory_enabled,
        "memory_top_k": run.memory_top_k,
        "optimizer_feedback": run.optimizer_feedback,
        "use_llm_optimizer_feedback": run.use_llm_optimizer_feedback,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "events": list(run.events),
        "prompt_rewrite": _prompt_rewrite_payload(run),
        "generation_goal": _read_json(run.output_dir / "generation_goal.json"),
        "memory_context": _read_json(run.output_dir / "memory_context.json"),
        "summary": _read_json(run.output_dir / "metrics.json") or run.summary,
        "trace": _read_json(run.output_dir / "llm_trace.json"),
        "baseline_validation": _read_json(run.output_dir / "baseline_validation.json"),
        "refined_validation": _read_json(run.output_dir / "refined_validation.json"),
        "raw_events": _read_jsonl(run.output_dir / "llm_raw_responses.jsonl") or run.raw_events,
    }
    payload["agent_workflow"] = _agent_workflow_payload(run, payload)
    if include_files:
        payload["artifacts"] = _artifact_payload(run)
    return payload


def _agent_workflow_payload(run: WebRun, payload: dict[str, Any]) -> list[dict[str, str]]:
    trace_rows = payload.get("trace")
    trace = trace_rows[0] if isinstance(trace_rows, list) and trace_rows and isinstance(trace_rows[0], dict) else {}
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    latest_stage = _latest_workflow_stage(events)
    statuses = {node["id"]: "waiting" for node in WORKFLOW_NODES}

    _mark_if_enabled(statuses, "memory", "done" if run.memory_enabled else "skipped")
    _apply_backend_status(statuses, "goal-manager", trace.get("goal_manager_backend"))
    _apply_backend_status(statuses, "prompt-rewriter", trace.get("rewriter_backend"))
    _apply_backend_status(statuses, "planner", trace.get("planner_backend"))
    _apply_backend_status(statuses, "svg-generator", trace.get("svg_backend"))
    _apply_backend_status(statuses, "optimizer", trace.get("optimizer_backend"))
    _apply_backend_status(statuses, "validator", trace.get("validator_backend"))
    _apply_backend_status(statuses, "failure-taxonomy", trace.get("failure_taxonomy_backend"))
    _apply_backend_status(statuses, "repair-router", trace.get("repair_router_backend"))
    _apply_backend_status(statuses, "refiner", trace.get("refiner_backend"))
    _apply_backend_status(statuses, "memory-curator", trace.get("memory_curator_backend"))

    if run.workflow == "single":
        for node_id in ("critic", "selector", "optimizer"):
            statuses[node_id] = "skipped"
    else:
        if trace.get("critic_reports"):
            statuses["critic"] = "done"
        if trace.get("selected_candidate_id"):
            statuses["selector"] = "done"

    if payload.get("summary"):
        statuses["exporter"] = "done"
    if run.status == "failed":
        error_node = _first_error_node(trace) or latest_stage or "pipeline"
        if error_node in statuses:
            statuses[error_node] = "error"
    if run.status in {"running", "queued", "optimizing"} and latest_stage in statuses:
        statuses[latest_stage] = "active"

    if run.status == "completed":
        for node_id in ("failure-taxonomy", "repair-router", "refiner"):
            if statuses[node_id] == "waiting":
                statuses[node_id] = "skipped"
        for node_id, status in list(statuses.items()):
            if status == "active":
                statuses[node_id] = "done"

    return [
        {
            "id": node["id"],
            "label": node["label"],
            "status": statuses[node["id"]],
        }
        for node in WORKFLOW_NODES
    ]


def _apply_backend_status(statuses: dict[str, str], node_id: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        return
    if value == "not-run":
        return
    if value == "skipped":
        statuses[node_id] = "skipped"
    elif "error" in value:
        statuses[node_id] = "error"
    else:
        statuses[node_id] = "done"


def _mark_if_enabled(statuses: dict[str, str], node_id: str, status: str) -> None:
    if statuses.get(node_id) == "waiting":
        statuses[node_id] = status


def _latest_workflow_stage(events: list[Any]) -> str | None:
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        stage = event.get("stage")
        if not isinstance(stage, str):
            continue
        node_id = STAGE_TO_NODE.get(stage)
        if node_id:
            return node_id
    return None


def _first_error_node(trace: dict[str, Any]) -> str | None:
    backend_fields = (
        ("goal-manager", "goal_manager_backend"),
        ("prompt-rewriter", "rewriter_backend"),
        ("planner", "planner_backend"),
        ("svg-generator", "svg_backend"),
        ("optimizer", "optimizer_backend"),
        ("validator", "validator_backend"),
        ("failure-taxonomy", "failure_taxonomy_backend"),
        ("repair-router", "repair_router_backend"),
        ("refiner", "refiner_backend"),
        ("memory-curator", "memory_curator_backend"),
    )
    for node_id, field_name in backend_fields:
        value = trace.get(field_name)
        if isinstance(value, str) and "error" in value:
            return node_id
    return None


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
    artifact_id = (
        _first_svg_id(run.output_dir / "refined")
        or _first_svg_id(run.output_dir / "baseline")
        or _first_svg_id(run.output_dir / "selected")
    )
    if not artifact_id:
        return {}
    files = {
        "selected_svg": Path("selected") / f"{artifact_id}.svg",
        "baseline_svg": Path("baseline") / f"{artifact_id}.svg",
        "refined_svg": Path("refined") / f"{artifact_id}.svg",
        "edited_svg": Path("edited") / f"{artifact_id}.svg",
        "baseline_png": Path("png/baseline") / f"{artifact_id}.png",
        "refined_png": Path("png/refined") / f"{artifact_id}.png",
        "edited_png": Path("png/edited") / f"{artifact_id}.png",
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
    edited_svg = run.output_dir / files["edited_svg"]
    if selected_svg.exists():
        artifacts["selected_svg_text"] = selected_svg.read_text(encoding="utf-8")
    if baseline_svg.exists():
        artifacts["baseline_svg_text"] = baseline_svg.read_text(encoding="utf-8")
    if refined_svg.exists():
        artifacts["refined_svg_text"] = refined_svg.read_text(encoding="utf-8")
    if edited_svg.exists():
        edited_text = edited_svg.read_text(encoding="utf-8")
        artifacts["edited_svg_text"] = edited_text
        report = SvgCheckTool().check(SvgArtifact(id=artifact_id, stage="edited", svg=edited_text))
        artifacts["edited_validation"] = report.to_json()
        metadata = _read_json(run.output_dir / "edited" / f"{artifact_id}.json")
        if isinstance(metadata, dict) and isinstance(metadata.get("source"), str):
            artifacts["edited_source"] = metadata["source"]
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


def _save_edited_svg(run: WebRun, *, svg: str, source: str) -> None:
    artifact_id = (
        _first_svg_id(run.output_dir / "refined")
        or _first_svg_id(run.output_dir / "baseline")
        or _first_svg_id(run.output_dir / "selected")
    )
    if not artifact_id:
        raise ValueError("Run does not contain an SVG artifact to edit.")
    source_path = run.output_dir / source / f"{artifact_id}.svg"
    if not source_path.exists():
        raise ValueError(f"Run does not contain a {source} SVG artifact.")

    report = SvgCheckTool().check(SvgArtifact(id=artifact_id, stage="edited", svg=svg))
    errors = [issue for issue in report.issues if issue.severity == "error"]
    if errors:
        messages = "; ".join(f"{issue.code}: {issue.message}" for issue in errors)
        raise ValueError(f"Edited SVG failed validation: {messages}")

    edited_dir = run.output_dir / "edited"
    png_dir = run.output_dir / "png" / "edited"
    edited_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)
    tmp_png = png_dir / f"{artifact_id}.tmp.png"
    png_path = png_dir / f"{artifact_id}.png"
    try:
        render_svg_to_png(svg, tmp_png)
    except Exception:
        tmp_png.unlink(missing_ok=True)
        raise

    (edited_dir / f"{artifact_id}.svg").write_text(svg, encoding="utf-8")
    (edited_dir / f"{artifact_id}.json").write_text(
        json.dumps({"source": source, "validation": report.to_json()}, indent=2),
        encoding="utf-8",
    )
    tmp_png.replace(png_path)


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


def _load_run_goal(output_dir: Path, artifact_id: str) -> GenerationGoal | None:
    data = _read_json(output_dir / "generation_goal.json")
    if not isinstance(data, dict):
        return None
    value = data.get(artifact_id)
    if not isinstance(value, dict):
        return None
    return GenerationGoal(
        objective=str(value.get("objective") or ""),
        visual_requirements=_text_tuple(value.get("visual_requirements")),
        constraints=_text_tuple(value.get("constraints")),
        acceptance_criteria=_text_tuple(value.get("acceptance_criteria")),
        style_preferences=_text_tuple(value.get("style_preferences")),
        avoid_patterns=_text_tuple(value.get("avoid_patterns")),
    )


def _load_run_memory_context(output_dir: Path, artifact_id: str) -> MemoryContext | None:
    data = _read_json(output_dir / "memory_context.json")
    if not isinstance(data, dict):
        return None
    value = data.get(artifact_id)
    if not isinstance(value, dict):
        return None
    records = []
    for item in value.get("records") or ():
        if not isinstance(item, dict):
            continue
        records.append(
            RetrievedMemory(
                record=MemoryRecord(
                    id=str(item.get("id") or ""),
                    source_path=str(item.get("source_path") or ""),
                    prompt=str(item.get("prompt") or ""),
                    summary=str(item.get("summary") or ""),
                    success_patterns=_text_tuple(item.get("success_patterns")),
                    failure_patterns=_text_tuple(item.get("failure_patterns")),
                    user_feedback=_text_tuple(item.get("user_feedback")),
                    score=_optional_int_value(item.get("score"), minimum=0, maximum=100),
                    tags=_text_tuple(item.get("tags")),
                ),
                score=float(item.get("retrieval_score") or 0),
            )
        )
    return MemoryContext(
        enabled=bool(value.get("enabled", True)),
        top_k=_int_value(value.get("top_k"), 3, minimum=0, maximum=10),
        query=str(value.get("query") or ""),
        records=tuple(records),
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
    (output_dir / "failure_taxonomy.json").write_text(
        json.dumps(
            [
                taxonomy.to_json()
                for result in refinements
                for taxonomy in result.failure_taxonomies
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "repair_routes.json").write_text(
        json.dumps(
            [
                route.to_json()
                for result in refinements
                for route in result.repair_routes
            ],
            indent=2,
        ),
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
    failure_taxonomy_backend: str | None = None,
    repair_router_backend: str | None = None,
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
    if failure_taxonomy_backend:
        item["failure_taxonomy_backend"] = failure_taxonomy_backend
    if repair_router_backend:
        item["repair_router_backend"] = repair_router_backend
    if refiner_backend:
        item["refiner_backend"] = refiner_backend
    taxonomy_rows = _read_json(output_dir / "failure_taxonomy.json")
    if isinstance(taxonomy_rows, list):
        item["failure_taxonomies"] = taxonomy_rows
    route_rows = _read_json(output_dir / "repair_routes.json")
    if isinstance(route_rows, list):
        item["repair_routes"] = route_rows
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
      grid-auto-rows: auto;
      align-content: start;
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
    .error-banner {
      border-color: #fecdca;
      background: #fef3f2;
      color: var(--bad);
      padding: 14px 16px;
      display: grid;
      gap: 6px;
      line-height: 1.45;
    }
    .error-banner[hidden] {
      display: none;
    }
    .error-banner strong {
      color: var(--bad);
    }
    .error-banner code {
      background: #fff;
      border: 1px solid #fecdca;
      border-radius: 4px;
      color: var(--ink);
      padding: 1px 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .memory-list {
      display: grid;
      gap: 8px;
      font-size: 13px;
      line-height: 1.4;
      color: var(--muted);
    }
    .memory-item {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fbfdff;
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
    .svg-editor {
      padding: 16px;
      display: grid;
      grid-template-rows: auto auto minmax(520px, 62vh) auto;
      gap: 12px;
      min-height: 680px;
    }
    .editor-toolbar {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) auto auto auto;
      gap: 10px;
      align-items: end;
    }
    .editor-toolbar button.secondary {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
    }
    .editor-grid {
      display: grid;
      grid-template-columns: minmax(320px, 1.2fr) minmax(260px, .8fr);
      gap: 12px;
      min-height: 0;
    }
    .editor-grid > div:first-child {
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .editor-grid textarea {
      min-height: 0;
      height: 100%;
      overflow: auto;
      resize: none;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.5;
      tab-size: 2;
    }
    .editor-preview-panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      display: grid;
      grid-template-rows: 36px minmax(0, 1fr) auto;
      background: #fbfdff;
      min-height: 0;
    }
    .editor-preview-panel .preview-box {
      overflow: auto;
    }
    .editor-validation {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-height: 42px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      background: #fff;
      white-space: pre-wrap;
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
    .workflow-dag {
      position: relative;
      width: 1810px;
      min-height: 390px;
      margin-bottom: 14px;
    }
    .workflow-node {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      width: 132px;
      min-height: 62px;
      background: #fff;
      display: grid;
      align-content: center;
      gap: 4px;
      position: absolute;
      z-index: 1;
    }
    .workflow-node strong {
      font-size: 12px;
      line-height: 1.2;
    }
    .workflow-node span {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .workflow-node.done {
      border-color: #a6f4c5;
      background: #ecfdf3;
    }
    .workflow-node.active {
      border-color: var(--accent);
      background: #eef6ff;
      box-shadow: 0 0 0 2px rgba(21, 112, 239, 0.14);
    }
    .workflow-node.error {
      border-color: #fecdca;
      background: #fef3f2;
    }
    .workflow-node.skipped {
      background: #f8fafc;
      color: var(--muted);
      opacity: 0.72;
    }
    .workflow-edges {
      position: absolute;
      inset: 0;
      width: 1810px;
      height: 390px;
      pointer-events: none;
    }
    .workflow-arrow {
      fill: none;
      stroke: var(--line);
      stroke-width: 2;
    }
    .workflow-arrow.done,
    .workflow-arrow.active {
      stroke: var(--accent);
    }
    .workflow-arrow.error {
      stroke: var(--bad);
    }
    .workflow-arrow.skipped {
      opacity: 0.42;
    }
    .workflow-marker {
      fill: var(--line);
    }
    .workflow-marker.done,
    .workflow-marker.active {
      fill: var(--accent);
    }
    .workflow-marker.error {
      fill: var(--bad);
    }
    .workflow-marker.skipped {
      opacity: 0.42;
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
      .svg-editor {
        min-height: 620px;
        grid-template-rows: auto auto minmax(460px, 65vh) auto;
      }
      .editor-toolbar { grid-template-columns: 1fr 1fr; }
      .editor-grid { grid-template-columns: 1fr; }
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
        <label for="goal">Goal</label>
        <textarea id="goal" style="min-height: 76px" placeholder="Optional generation goal, e.g. suitable for a mobile toolbar"></textarea>
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
        <input id="useMemory" type="checkbox" checked>
        Use historical memory
      </label>
      <div>
        <label for="memoryTopK">Memory top-k</label>
        <input id="memoryTopK" type="number" min="0" max="10" value="3">
      </div>
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
      <section id="errorBanner" class="error-banner" hidden></section>
      <section class="prompt-panel">
        <h2>Goal, Memory, Prompt Rewrite</h2>
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
        <div class="prompt-compare">
          <div>
            <label>Generation Goal</label>
            <div id="goalOutput" class="prompt-box">Waiting for Goal Manager Agent</div>
          </div>
          <div>
            <label>Retrieved Memories</label>
            <div id="memoryOutput" class="prompt-box">Waiting for MemoryRetrievalTool</div>
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
      <section class="svg-editor">
        <h2>SVG Editor</h2>
        <div class="editor-toolbar">
          <div>
            <label for="editorSource">Source</label>
            <select id="editorSource" disabled>
              <option value="">No SVG available</option>
            </select>
          </div>
          <button id="resetSvgEditor" class="secondary" type="button" disabled>Reset</button>
          <button id="validateSvgEditor" class="secondary" type="button" disabled>Validate</button>
          <button id="saveSvgEditor" type="button" disabled>Save edited SVG</button>
        </div>
        <div class="editor-grid">
          <div>
            <label for="svgEditorText">SVG source</label>
            <textarea id="svgEditorText" spellcheck="false" disabled></textarea>
          </div>
          <div class="editor-preview-panel">
            <div class="figure-title">Live Preview</div>
            <div id="svgEditorPreview" class="preview-box svg-preview"><div class="empty">No editable SVG</div></div>
            <figcaption id="editedSvgCaption">No edited SVG saved</figcaption>
          </div>
        </div>
        <div id="svgEditorStatus" class="editor-validation">Waiting for generated SVG</div>
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
    const state = {
      runId: null,
      timer: null,
      activeTab: 'timeline',
      latestRun: null,
      artifacts: {},
      editorDirty: false,
      editorArtifactId: null,
      editorUseSaved: false,
      editorPreviewTimer: null
    };
    const runButton = document.getElementById('runButton');
    const optimizeButton = document.getElementById('optimizeButton');
    const statusBox = document.getElementById('status');
    const runIdBox = document.getElementById('runId');
    const runStateBox = document.getElementById('runState');
    const errorBanner = document.getElementById('errorBanner');
    const editorSource = document.getElementById('editorSource');
    const svgEditorText = document.getElementById('svgEditorText');
    const svgEditorPreview = document.getElementById('svgEditorPreview');
    const svgEditorStatus = document.getElementById('svgEditorStatus');
    const resetSvgEditor = document.getElementById('resetSvgEditor');
    const validateSvgEditor = document.getElementById('validateSvgEditor');
    const saveSvgEditor = document.getElementById('saveSvgEditor');
    const editedSvgCaption = document.getElementById('editedSvgCaption');

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
        goal: document.getElementById('goal').value,
        model: document.getElementById('model').value,
        max_refine_rounds: Number(document.getElementById('rounds').value),
        workflow: document.getElementById('workflow').value,
        candidate_count: Number(document.getElementById('candidateCount').value),
        rewrite_prompt: document.getElementById('rewritePrompt').checked,
        memory_enabled: document.getElementById('useMemory').checked,
        memory_top_k: Number(document.getElementById('memoryTopK').value),
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
      hideErrorBanner();
      clearInterval(state.timer);
      resetEditorState();
      const response = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        runButton.disabled = false;
        setStatus(data.error || 'Run could not start.', 'bad');
        showErrorBanner(data.error || 'Run could not start.');
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
      hideErrorBanner();
      clearInterval(state.timer);
      const response = await fetch(`/api/runs/${state.runId}/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.error || 'Post-run optimization could not start.', 'bad');
        showErrorBanner(data.error || 'Post-run optimization could not start.');
        runButton.disabled = false;
        optimizeButton.disabled = false;
        return;
      }
      renderRun(data);
      state.timer = setInterval(() => pollRun(), 1200);
    });

    editorSource.addEventListener('change', () => {
      state.editorUseSaved = false;
      state.editorDirty = false;
      loadEditorSource(editorSource.value);
      syncEditorButtons(state.latestRun || {});
    });

    svgEditorText.addEventListener('input', () => {
      state.editorDirty = true;
      state.editorUseSaved = false;
      clearTimeout(state.editorPreviewTimer);
      state.editorPreviewTimer = setTimeout(() => updateEditorPreview(), 120);
      syncEditorButtons(state.latestRun || {});
    });

    resetSvgEditor.addEventListener('click', () => {
      state.editorUseSaved = false;
      state.editorDirty = false;
      loadEditorSource(editorSource.value);
      syncEditorButtons(state.latestRun || {});
    });

    validateSvgEditor.addEventListener('click', () => {
      updateEditorPreview({ message: 'Local SVG preview validation passed.' });
    });

    saveSvgEditor.addEventListener('click', async () => {
      if (!state.runId) {
        setEditorValidation('Run an icon pipeline before saving edited SVG.', 'bad');
        return;
      }
      const source = editorSource.value;
      const svg = svgEditorText.value.trim();
      if (!source || !svg) {
        setEditorValidation('Choose a source and enter SVG text before saving.', 'bad');
        return;
      }
      if (!updateEditorPreview({ message: 'Local SVG preview validation passed.' })) {
        return;
      }
      saveSvgEditor.disabled = true;
      setEditorValidation('Saving edited SVG...', '');
      const response = await fetch(`/api/runs/${state.runId}/edited-svg`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ svg, source })
      });
      const data = await response.json();
      if (!response.ok) {
        setEditorValidation(data.error || 'Edited SVG could not be saved.', 'bad');
        syncEditorButtons(state.latestRun || {});
        return;
      }
      state.editorDirty = false;
      state.editorUseSaved = true;
      renderRun(data);
      setStatus('Edited SVG saved.', 'ok');
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
      state.latestRun = data;
      runIdBox.textContent = data.id || 'No run';
      runStateBox.textContent = data.status || 'unknown';
      runStateBox.className = `pill ${data.status === 'completed' ? 'ok' : data.status === 'failed' ? 'bad' : ''}`;
      setStatus(data.error || statusText(data), data.status === 'failed' ? 'bad' : data.status === 'completed' ? 'ok' : '');
      renderErrorBanner(data);
      renderTimeline(data.events || [], data.agent_workflow || []);
      renderJson('trace', data.trace || data.summary || {});
      renderJson('raw', data.raw_events || []);
      renderPromptRewrite(data);
      renderGoalAndMemory(data);
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

    function renderErrorBanner(data) {
      if (data.status === 'failed' || data.error) {
        showErrorBanner(data.error || 'Run failed.');
        return;
      }
      hideErrorBanner();
    }

    function showErrorBanner(error) {
      const text = String(error || 'Run failed.');
      const hint = text.includes('OPENROUTER_API_KEY')
        ? 'Add OPENROUTER_API_KEY to .env or export it before starting web.py, then restart the Web UI.'
        : 'Check the Flow and Raw LLM tabs for the failing stage details.';
      errorBanner.hidden = false;
      errorBanner.innerHTML = `
        <strong>Run failed before SVG generation completed.</strong>
        <div>${escapeHtml(text)}</div>
        <div>${inlineCodeHint(hint)}</div>
      `;
    }

    function hideErrorBanner() {
      errorBanner.hidden = true;
      errorBanner.innerHTML = '';
    }

    function inlineCodeHint(text) {
      return escapeHtml(text).replace(/OPENROUTER_API_KEY|\\.env|web\\.py/g, (match) => `<code>${match}</code>`);
    }

    function syncButtons(data) {
      const busy = ['queued', 'running', 'optimizing'].includes(data.status);
      runButton.disabled = busy;
      optimizeButton.disabled = busy || !data.id || !(data.artifacts && (data.artifacts.refined_svg_text || data.artifacts.baseline_svg_text));
      syncEditorButtons(data);
    }

    function renderTimeline(events, workflow) {
      const box = document.getElementById('timeline');
      const workflowHtml = workflow.length ? renderWorkflowGraph(workflow) : '';
      const timelineHtml = events.length ? `
        <div class="timeline">${events.map((event) => `
          <div class="event">
            <span>${Number(event.elapsed || 0).toFixed(1)}s</span>
            <span class="stage">${escapeHtml(event.stage || 'pipeline')}</span>
            <span>${escapeHtml(event.message || '')}</span>
          </div>
        `).join('')}</div>
      ` : '<div class="empty">No flow events</div>';
      box.innerHTML = workflowHtml + timelineHtml;
    }

    function renderWorkflowGraph(workflow) {
      const statusById = workflowStatusById(workflow);
      const nodes = workflowGraphNodes(statusById);
      const nodeById = Object.fromEntries(nodes.map((node) => [node.id, node]));
      const edges = workflowGraphEdges();
      const edgeLayer = renderWorkflowEdges(edges, nodeById);
      const nodeLayer = nodes.map((node) => `
        <div class="workflow-node ${escapeHtml(node.status)}"
          style="left: ${node.x}px; top: ${node.y}px"
          title="${escapeHtml(node.id)}">
          <strong>${escapeHtml(node.label)}</strong>
          <span>${escapeHtml(node.status)}</span>
        </div>
      `).join('');
      return `<div class="workflow-dag" aria-label="Directed Agent dependency graph">${edgeLayer}${nodeLayer}</div>`;
    }

    function workflowStatusById(workflow) {
      return Object.fromEntries(workflow.map((node) => [node.id, node.status || 'waiting']));
    }

    function workflowGraphNodes(statusById) {
      return [
        graphNode('memory', 'Memory', 20, 150, statusById.memory),
        graphNode('goal-manager', 'Goal Manager', 180, 150, statusById['goal-manager']),
        graphNode('prompt-rewriter', 'Prompt Rewriter', 340, 150, statusById['prompt-rewriter']),
        graphNode('planner', 'Planner', 500, 150, statusById.planner),
        graphNode('candidate-generator', 'Candidate Generators', 660, 150, statusById['svg-generator']),
        graphNode('semantic-critic', 'Semantic Critic', 840, 70, statusById.critic),
        graphNode('svg-quality-critic', 'SVG Quality Critic', 840, 230, statusById.critic),
        graphNode('selector', 'Consensus Selector', 1020, 150, statusById.selector),
        graphNode('optimizer', 'SVG Optimizer', 1180, 150, statusById.optimizer),
        graphNode('validator', 'Validator', 1340, 150, statusById.validator),
        graphNode('failure-taxonomy', 'Failure Taxonomy', 1500, 70, statusById['failure-taxonomy']),
        graphNode('repair-router', 'Repair Router', 1660, 70, statusById['repair-router']),
        graphNode('refiner', 'Refiner', 1660, 230, statusById.refiner),
        graphNode('exporter', 'Exporter', 1500, 310, statusById.exporter),
        graphNode('memory-curator', 'Memory Curator', 1660, 310, statusById['memory-curator'])
      ];
    }

    function graphNode(id, label, x, y, status) {
      return { id, label, x, y, status: status || 'waiting', width: 132, height: 62 };
    }

    function workflowGraphEdges() {
      return [
        ['memory', 'goal-manager'],
        ['goal-manager', 'prompt-rewriter'],
        ['prompt-rewriter', 'planner'],
        ['planner', 'candidate-generator'],
        ['candidate-generator', 'semantic-critic'],
        ['candidate-generator', 'svg-quality-critic'],
        ['semantic-critic', 'selector'],
        ['svg-quality-critic', 'selector'],
        ['selector', 'optimizer'],
        ['optimizer', 'validator'],
        ['validator', 'failure-taxonomy'],
        ['failure-taxonomy', 'repair-router'],
        ['repair-router', 'refiner'],
        ['refiner', 'validator'],
        ['validator', 'exporter'],
        ['exporter', 'memory-curator']
      ];
    }

    function renderWorkflowEdges(edges, nodeById) {
      const markers = ['waiting', 'done', 'active', 'error', 'skipped'].map((status) => `
        <marker id="arrow-${status}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" class="workflow-marker ${status}"></path>
        </marker>
      `).join('');
      const paths = edges.map(([fromId, toId]) => {
        const from = nodeById[fromId];
        const to = nodeById[toId];
        if (!from || !to) return '';
        const status = edgeStatus(from.status, to.status);
        return `<path class="workflow-arrow ${escapeHtml(status)}" marker-end="url(#arrow-${escapeHtml(status)})" d="${escapeHtml(edgePath(from, to))}"></path>`;
      }).join('');
      return `<svg class="workflow-edges" viewBox="0 0 1810 390" aria-hidden="true">
        <defs>${markers}</defs>
        ${paths}
      </svg>`;
    }

    function edgePath(from, to) {
      const fromRight = from.x + from.width;
      const fromLeft = from.x;
      const fromY = from.y + from.height / 2;
      const toLeft = to.x;
      const toRight = to.x + to.width;
      const toY = to.y + to.height / 2;
      if (from.x > to.x) {
        const startX = fromLeft;
        const endX = toRight;
        const midY = Math.max(fromY, toY) + 54;
        return `M ${startX} ${fromY} C ${startX - 80} ${midY}, ${endX + 80} ${midY}, ${endX} ${toY}`;
      }
      const midX = (fromRight + toLeft) / 2;
      return `M ${fromRight} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toLeft} ${toY}`;
    }

    function edgeStatus(currentStatus, nextStatus) {
      if (currentStatus === 'error' || nextStatus === 'error') return 'error';
      if (nextStatus === 'active') return 'active';
      if (currentStatus === 'done' || currentStatus === 'skipped') return currentStatus;
      return 'waiting';
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
      renderSvgEditor(artifacts);
    }

    function resetEditorState() {
      state.artifacts = {};
      state.editorDirty = false;
      state.editorArtifactId = null;
      state.editorUseSaved = false;
      clearTimeout(state.editorPreviewTimer);
      editorSource.innerHTML = '<option value="">No SVG available</option>';
      editorSource.value = '';
      svgEditorText.value = '';
      svgEditorPreview.innerHTML = '<div class="empty">No editable SVG</div>';
      editedSvgCaption.textContent = 'No edited SVG saved';
      setEditorValidation('Waiting for generated SVG', '');
      syncEditorButtons({});
    }

    function renderSvgEditor(artifacts) {
      state.artifacts = artifacts || {};
      const sources = editableSources(state.artifacts);
      const artifactId = state.artifacts.id || null;
      const artifactChanged = state.editorArtifactId !== artifactId;
      if (!sources.length) {
        resetEditorState();
        state.editorArtifactId = artifactId;
        return;
      }

      const previousSource = editorSource.value;
      editorSource.innerHTML = sources.map((source) => `
        <option value="${escapeHtml(source.value)}">${escapeHtml(source.label)}</option>
      `).join('');
      const hasPreviousSource = sources.some((source) => source.value === previousSource);
      editorSource.value = hasPreviousSource ? previousSource : sources[0].value;

      if (artifactChanged || !state.editorDirty) {
        state.editorArtifactId = artifactId;
        if (state.editorUseSaved && state.artifacts.edited_svg_text) {
          svgEditorText.value = state.artifacts.edited_svg_text;
        } else {
          svgEditorText.value = sourceText(state.artifacts, editorSource.value);
        }
        state.editorDirty = false;
        updateEditorPreview({ keepStatus: true });
      }

      renderEditedCaption(state.artifacts);
      if (!state.editorDirty) {
        renderEditedValidation(state.artifacts);
      }
      syncEditorButtons(state.latestRun || {});
    }

    function editableSources(artifacts) {
      return [
        { value: 'refined', label: 'Refined SVG', text: artifacts.refined_svg_text },
        { value: 'baseline', label: 'Optimized baseline SVG', text: artifacts.baseline_svg_text },
        { value: 'selected', label: 'Selected SVG', text: artifacts.selected_svg_text }
      ].filter((source) => source.text);
    }

    function sourceText(artifacts, source) {
      if (source === 'refined') return artifacts.refined_svg_text || '';
      if (source === 'baseline') return artifacts.baseline_svg_text || '';
      if (source === 'selected') return artifacts.selected_svg_text || '';
      return '';
    }

    function loadEditorSource(source) {
      svgEditorText.value = sourceText(state.artifacts, source);
      updateEditorPreview({ message: `Loaded ${source || 'source'} SVG.` });
      renderEditedCaption(state.artifacts);
    }

    function renderEditedCaption(artifacts) {
      if (artifacts.edited_svg_url) {
        const source = artifacts.edited_source ? ` from ${artifacts.edited_source}` : '';
        editedSvgCaption.textContent = `${artifacts.edited_svg_url}${source}`;
        return;
      }
      editedSvgCaption.textContent = 'No edited SVG saved';
    }

    function renderEditedValidation(artifacts) {
      const validation = artifacts.edited_validation;
      if (!validation) {
        setEditorValidation(`Loaded ${editorSource.value || 'source'} SVG. Live preview is ready.`, 'ok');
        return;
      }
      const issues = Array.isArray(validation.issues) ? validation.issues : [];
      if (!issues.length) {
        setEditorValidation(`Saved edited SVG is valid. Score ${validation.score}.`, 'ok');
        return;
      }
      const summary = issues.map((issue) => `${issue.severity}: ${issue.code} - ${issue.message}`).join('\\n');
      setEditorValidation(summary, validation.is_valid ? 'warn' : 'bad');
    }

    function updateEditorPreview(options = {}) {
      const svg = svgEditorText.value.trim();
      if (!svg) {
        svgEditorPreview.innerHTML = '<div class="empty">No editable SVG</div>';
        setEditorValidation('SVG source is empty.', 'bad');
        return false;
      }
      const result = validateSvgForPreview(svg);
      if (!result.ok) {
        svgEditorPreview.innerHTML = '<div class="empty">Preview paused until SVG is valid</div>';
        setEditorValidation(result.errors.join('\\n'), 'bad');
        return false;
      }
      svgEditorPreview.replaceChildren(document.importNode(result.root, true));
      if (!options.keepStatus) {
        setEditorValidation(options.message || 'Preview updated locally.', state.editorDirty ? 'warn' : 'ok');
      }
      return true;
    }

    function validateSvgForPreview(svg) {
      const parser = new DOMParser();
      const documentXml = parser.parseFromString(svg, 'image/svg+xml');
      const errors = [];
      if (documentXml.querySelector('parsererror')) {
        errors.push('SVG XML is not parseable.');
      }
      const root = documentXml.documentElement;
      if (!root || localSvgName(root) !== 'svg') {
        errors.push('Root element must be <svg>.');
      }
      const disallowedTags = new Set(['script', 'foreignobject', 'image', 'iframe', 'audio', 'video', 'animate']);
      if (root) {
        [root, ...Array.from(root.querySelectorAll('*'))].forEach((element) => {
          const tag = localSvgName(element);
          if (disallowedTags.has(tag)) {
            errors.push(`Disallowed tag <${tag}> found.`);
          }
          Array.from(element.attributes || []).forEach((attribute) => {
            const name = localSvgName(attribute);
            const value = String(attribute.value || '').toLowerCase();
            if (name.startsWith('on')) {
              errors.push(`Event handler attribute ${name} is not allowed.`);
            }
            if (name === 'href' || name === 'src') {
              errors.push(`External reference attribute ${name} is not allowed.`);
            }
            if (value.includes('javascript:') || value.includes('url(')) {
              errors.push(`Unsafe reference found in ${name}.`);
            }
          });
        });
      }
      return { ok: errors.length === 0, errors, root };
    }

    function localSvgName(node) {
      return String(node.localName || node.name || node.nodeName || '').toLowerCase();
    }

    function setEditorValidation(text, cls) {
      svgEditorStatus.textContent = text;
      svgEditorStatus.className = `editor-validation ${cls || ''}`;
    }

    function syncEditorButtons(data) {
      const busy = ['queued', 'running', 'optimizing'].includes(data.status);
      const hasSources = editableSources(state.artifacts || {}).length > 0;
      editorSource.disabled = !hasSources;
      svgEditorText.disabled = !hasSources;
      resetSvgEditor.disabled = !hasSources;
      validateSvgEditor.disabled = !hasSources;
      saveSvgEditor.disabled = busy || !data.id || !hasSources || !svgEditorText.value.trim();
    }

    function renderPromptRewrite(data) {
      const traceItem = data.trace && data.trace[0] ? data.trace[0] : {};
      const liveRewrite = data.prompt_rewrite || {};
      document.getElementById('originalPrompt').textContent =
        liveRewrite.original_prompt || traceItem.original_prompt || data.prompt || 'Waiting for input';
      document.getElementById('rewrittenPrompt').textContent =
        liveRewrite.rewritten_prompt || traceItem.rewritten_prompt || 'Waiting for Prompt Rewriter Agent';
    }

    function renderGoalAndMemory(data) {
      const traceItem = data.trace && data.trace[0] ? data.trace[0] : {};
      const artifactId = data.artifacts && data.artifacts.id ? data.artifacts.id : traceItem.id;
      const goals = data.generation_goal || {};
      const goal = artifactId && goals[artifactId] ? goals[artifactId] : null;
      document.getElementById('goalOutput').textContent = goal
        ? `${goal.objective || ''}\\nRequirements: ${(goal.visual_requirements || []).join(', ')}\\nAccept: ${(goal.acceptance_criteria || []).join(', ')}\\nAvoid: ${(goal.avoid_patterns || []).join(', ')}`
        : 'Waiting for Goal Manager Agent';
      const contexts = data.memory_context || {};
      const context = artifactId && contexts[artifactId] ? contexts[artifactId] : null;
      if (!context || !Array.isArray(context.records) || !context.records.length) {
        document.getElementById('memoryOutput').innerHTML = '<div>No retrieved memories</div>';
        return;
      }
      document.getElementById('memoryOutput').innerHTML = `<div class="memory-list">${context.records.map((record) => `
        <div class="memory-item">
          <strong>${escapeHtml(record.id || 'memory')}</strong> score ${escapeHtml(record.retrieval_score || 0)}<br>
          ${escapeHtml(record.summary || record.prompt || '')}<br>
          Feedback: ${escapeHtml((record.user_feedback || []).join('; ') || 'none')}
        </div>
      `).join('')}</div>`;
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
</html>"""
