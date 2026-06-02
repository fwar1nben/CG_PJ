"""Shared pipeline runner for CLI and Web UI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from svg_icon_agent.backends import BackendTrace, OpenRouterClient, create_openrouter_client, generate_with_backend
from svg_icon_agent.exporter import export_artifacts
from svg_icon_agent.models import IconPlan, SvgArtifact, ValidationReport
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL, OpenRouterError
from svg_icon_agent.progress import ProgressLogger
from svg_icon_agent.prompts import PromptItem
from svg_icon_agent.refiner import RefinementResult, refine_artifacts

REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}


@dataclass
class EventProgressLogger(ProgressLogger):
    """Progress logger that stores events for the Web UI."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def log(self, message: str) -> None:
        elapsed = self.elapsed_seconds()
        self.events.append(
            {
                "elapsed": round(elapsed, 1),
                "message": message,
                "stage": _stage_from_message(message),
            }
        )
        if self.verbose:
            print(f"[{elapsed:6.1f}s] {message}", flush=True)

    def elapsed_seconds(self) -> float:
        import time

        return time.monotonic() - self.started_at


@dataclass(frozen=True)
class PipelineRunResult:
    status: str
    output_dir: Path
    prompts: list[PromptItem]
    plans: list[IconPlan]
    candidate_artifacts: list[SvgArtifact]
    baseline_artifacts: list[SvgArtifact]
    refined_artifacts: list[SvgArtifact]
    baseline_reports: list[ValidationReport]
    refined_reports: list[ValidationReport]
    refinements: list[RefinementResult]
    traces: list[BackendTrace]
    raw_events: list[dict[str, Any]]
    summary: dict[str, object] = field(default_factory=dict)
    error: str | None = None


def run_single_prompt_pipeline(
    prompt: PromptItem,
    *,
    output_dir: Path,
    model: str = DEFAULT_OPENROUTER_MODEL,
    max_refine_rounds: int = 3,
    request_timeout: float = 60.0,
    max_retries: int = 2,
    max_tokens: int | None = None,
    reasoning_effort: str | None = "none",
    reasoning_max_tokens: int | None = None,
    workflow: str = "collaborative",
    candidate_count: int = 3,
    client: OpenRouterClient | None = None,
    progress: ProgressLogger | None = None,
) -> PipelineRunResult:
    return run_prompt_pipeline(
        [prompt],
        output_dir=output_dir,
        model=model,
        max_refine_rounds=max_refine_rounds,
        request_timeout=request_timeout,
        max_retries=max_retries,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        reasoning_max_tokens=reasoning_max_tokens,
        workflow=workflow,
        candidate_count=candidate_count,
        client=client,
        progress=progress,
    )


def run_prompt_pipeline(
    prompts: list[PromptItem],
    *,
    output_dir: Path,
    model: str = DEFAULT_OPENROUTER_MODEL,
    max_refine_rounds: int = 3,
    request_timeout: float = 60.0,
    max_retries: int = 2,
    max_tokens: int | None = None,
    reasoning_effort: str | None = "none",
    reasoning_max_tokens: int | None = None,
    workflow: str = "collaborative",
    candidate_count: int = 3,
    client: OpenRouterClient | None = None,
    progress: ProgressLogger | None = None,
) -> PipelineRunResult:
    logger = progress or ProgressLogger(verbose=False)
    reasoning = make_reasoning_config(reasoning_effort, reasoning_max_tokens)
    candidate_dir = output_dir / "candidates"
    baseline_dir = output_dir / "baseline"
    refined_dir = output_dir / "refined"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)

    logger.log(f"Loaded {len(prompts)} prompt(s).")
    try:
        active_client = client or create_openrouter_client(
            model=model,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
        backend_result = generate_with_backend(
            prompts,
            backend="openrouter",
            model=model,
            llm_stage="plan-svg",
            client=active_client,
            request_timeout=request_timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            reasoning=reasoning,
            workflow=workflow,
            candidate_count=candidate_count,
            progress=logger,
        )
    except (OpenRouterError, ValueError) as exc:
        logger.log(f"OpenRouter pipeline setup failed: {exc}")
        return PipelineRunResult(
            status="failed",
            output_dir=output_dir,
            prompts=prompts,
            plans=[],
            candidate_artifacts=[],
            baseline_artifacts=[],
            refined_artifacts=[],
            baseline_reports=[],
            refined_reports=[],
            refinements=[],
            traces=[],
            raw_events=[],
            error=str(exc),
        )

    plans = backend_result.plans
    artifacts = backend_result.artifacts
    candidate_artifacts = backend_result.candidate_artifacts
    trace_by_id = {trace.id: trace for trace in backend_result.traces}

    if candidate_artifacts:
        logger.log(f"Writing {len(candidate_artifacts)} candidate SVG files.")
    for artifact in candidate_artifacts:
        (candidate_dir / f"{artifact.id}-{artifact.stage}.svg").write_text(artifact.svg, encoding="utf-8")

    logger.log(f"Writing {len(artifacts)} baseline SVG files.")
    for artifact in artifacts:
        (baseline_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")

    if not artifacts:
        _write_trace_outputs(output_dir, backend_result.traces, backend_result.raw_llm_events)
        logger.log("No SVG artifacts were generated.")
        return PipelineRunResult(
            status="failed",
            output_dir=output_dir,
            prompts=prompts,
            plans=plans,
            candidate_artifacts=candidate_artifacts,
            baseline_artifacts=[],
            refined_artifacts=[],
            baseline_reports=[],
            refined_reports=[],
            refinements=[],
            traces=backend_result.traces,
            raw_events=backend_result.raw_llm_events,
            error="No SVG artifacts were generated.",
        )

    logger.log("Running LLM validation/refinement loop.")
    refinements = refine_artifacts(
        plans,
        artifacts,
        client=active_client,
        max_rounds=max_refine_rounds,
        model=model,
        max_tokens=max_tokens,
        reasoning=reasoning,
        collaboration_briefs=backend_result.selection_briefs,
        progress=logger,
    )
    _merge_refinement_traces(trace_by_id, refinements)

    refined_artifacts = [result.artifact for result in refinements]
    baseline_reports = [result.baseline_report for result in refinements]
    refined_reports = [result.refined_report for result in refinements]

    logger.log(f"Writing {len(refined_artifacts)} refined SVG files.")
    for artifact in refined_artifacts:
        (refined_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")

    raw_events = list(backend_result.raw_llm_events)
    for result in refinements:
        raw_events.extend(result.raw_llm_events)

    logger.log("Writing JSON reports and LLM trace.")
    _write_json_outputs(
        output_dir=output_dir,
        plans=plans,
        baseline_reports=baseline_reports,
        refined_reports=refined_reports,
        refinements=refinements,
    )
    _write_trace_outputs(output_dir, backend_result.traces, raw_events, baseline_reports, refined_reports)

    logger.log("Exporting PNG previews and gallery.")
    successful_prompts = [item for item in prompts if item.id in {artifact.id for artifact in refined_artifacts}]
    summary = export_artifacts(
        output_dir=output_dir,
        prompts=successful_prompts,
        baseline_artifacts=artifacts,
        refined_artifacts=refined_artifacts,
        baseline_reports=baseline_reports,
        refined_reports=refined_reports,
        refinements=refinements,
    )
    logger.log("Pipeline complete.")
    return PipelineRunResult(
        status="completed",
        output_dir=output_dir,
        prompts=prompts,
        plans=plans,
        candidate_artifacts=candidate_artifacts,
        baseline_artifacts=artifacts,
        refined_artifacts=refined_artifacts,
        baseline_reports=baseline_reports,
        refined_reports=refined_reports,
        refinements=refinements,
        traces=backend_result.traces,
        raw_events=raw_events,
        summary=summary,
    )


def _merge_refinement_traces(
    trace_by_id: dict[str, BackendTrace],
    refinements: list[RefinementResult],
) -> None:
    for result in refinements:
        trace = trace_by_id.get(result.id)
        if trace is None:
            continue
        trace.validator_backend = result.agent_statuses.get("validator", "not-run")
        trace.refiner_backend = result.agent_statuses.get("refiner", "not-run")
        trace.usage.update(result.usage)
        trace.errors.extend(result.errors)


def _write_json_outputs(
    *,
    output_dir: Path,
    plans: list[IconPlan],
    baseline_reports: list[ValidationReport],
    refined_reports: list[ValidationReport],
    refinements: list[RefinementResult],
) -> None:
    (output_dir / "plans.json").write_text(
        json.dumps([plan.to_json() for plan in plans], indent=2),
        encoding="utf-8",
    )
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


def _write_trace_outputs(
    output_dir: Path,
    traces: list[BackendTrace],
    raw_events: list[dict[str, object]],
    baseline_reports: list[ValidationReport] | None = None,
    refined_reports: list[ValidationReport] | None = None,
) -> None:
    baseline_by_id = {report.id: report for report in baseline_reports or []}
    refined_by_id = {report.id: report for report in refined_reports or []}
    (output_dir / "llm_trace.json").write_text(
        json.dumps(
            [
                trace.to_json(
                    baseline_report=baseline_by_id.get(trace.id),
                    refined_report=refined_by_id.get(trace.id),
                )
                for trace in traces
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "llm_raw_responses.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in raw_events),
        encoding="utf-8",
    )


def _stage_from_message(message: str) -> str:
    lowered = message.lower()
    if "plan" in lowered or "planner" in lowered:
        return "planner"
    if "svg draft" in lowered or "baseline svg" in lowered:
        return "svg-generator"
    if "candidate" in lowered:
        return "candidate-generator"
    if "critic" in lowered:
        return "critic"
    if "selector" in lowered:
        return "selector"
    if "svg check" in lowered:
        return "svg-check"
    if "validator" in lowered or "validation" in lowered:
        return "validator"
    if "refiner" in lowered or "refinement" in lowered:
        return "refiner"
    if "export" in lowered or "gallery" in lowered or "png" in lowered:
        return "exporter"
    if "error" in lowered or "failed" in lowered:
        return "error"
    return "pipeline"


def make_reasoning_config(
    reasoning_effort: str | None = "none",
    reasoning_max_tokens: int | None = None,
) -> dict[str, Any] | None:
    if reasoning_max_tokens is not None:
        return {
            "max_tokens": max(0, reasoning_max_tokens),
            "exclude": True,
        }
    effort = (reasoning_effort or "").strip().lower()
    if not effort:
        return None
    if effort not in REASONING_EFFORTS:
        raise ValueError(f"Unsupported reasoning effort: {reasoning_effort}")
    return {
        "effort": effort,
        "exclude": True,
    }
