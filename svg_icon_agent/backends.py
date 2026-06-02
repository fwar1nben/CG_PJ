"""OpenRouter backend orchestration for LLM-backed icon generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from svg_icon_agent.llm_agents import OpenRouterPlannerAgent, OpenRouterSvgGeneratorAgent
from svg_icon_agent.models import IconPlan, SvgArtifact, ValidationReport
from svg_icon_agent.openrouter_client import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterClient,
    OpenRouterConfig,
    OpenRouterError,
)
from svg_icon_agent.progress import ProgressLogger
from svg_icon_agent.prompts import PromptItem


@dataclass
class BackendTrace:
    id: str
    requested_backend: str
    model: str
    llm_stage: str
    planner_backend: str = "not-run"
    svg_backend: str = "not-run"
    validator_backend: str = "not-run"
    refiner_backend: str = "not-run"
    fallback_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_json(
        self,
        baseline_report: ValidationReport | None = None,
        refined_report: ValidationReport | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "requested_backend": self.requested_backend,
            "model": self.model,
            "llm_stage": self.llm_stage,
            "planner_backend": self.planner_backend,
            "svg_backend": self.svg_backend,
            "validator_backend": self.validator_backend,
            "refiner_backend": self.refiner_backend,
            "fallback_reason": self.fallback_reason,
            "usage": self.usage,
            "errors": self.errors,
        }
        if baseline_report is not None:
            data["baseline_score"] = baseline_report.score
            data["baseline_valid"] = baseline_report.is_valid
        if refined_report is not None:
            data["refined_score"] = refined_report.score
            data["refined_valid"] = refined_report.is_valid
        if baseline_report is not None and refined_report is not None:
            data["score_delta"] = refined_report.score - baseline_report.score
        return data


@dataclass(frozen=True)
class BackendResult:
    plans: list[IconPlan]
    artifacts: list[SvgArtifact]
    traces: list[BackendTrace]
    active_backend: str
    raw_llm_events: list[dict[str, Any]] = field(default_factory=list)


def create_openrouter_client(
    *,
    model: str | None = None,
    request_timeout: float | None = None,
    max_retries: int | None = None,
) -> OpenRouterClient:
    return OpenRouterClient(
        OpenRouterConfig.from_env(
            model=model or DEFAULT_OPENROUTER_MODEL,
            timeout=request_timeout,
            max_retries=max_retries,
        )
    )


def generate_with_backend(
    prompts: list[PromptItem],
    *,
    backend: str,
    model: str | None = None,
    llm_stage: str = "plan-svg",
    client: OpenRouterClient | None = None,
    request_timeout: float | None = None,
    max_retries: int | None = None,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
    progress: ProgressLogger | None = None,
) -> BackendResult:
    if backend != "openrouter":
        raise ValueError("Only the OpenRouter backend is supported; local rule generation has been removed.")
    if llm_stage != "plan-svg":
        raise ValueError("Only llm_stage=plan-svg is supported because SVG generation must be model-backed.")

    model_name = model or DEFAULT_OPENROUTER_MODEL
    logger = progress or ProgressLogger(verbose=False)
    openrouter_client = client or create_openrouter_client(
        model=model_name,
        request_timeout=request_timeout,
        max_retries=max_retries,
    )

    timeout = getattr(getattr(openrouter_client, "config", None), "timeout", request_timeout)
    retries = getattr(getattr(openrouter_client, "config", None), "max_retries", max_retries)
    logger.log(f"Using OpenRouter backend for {len(prompts)} prompts (timeout={timeout}s, retries={retries}).")
    return _openrouter_backend(
        prompts,
        requested_backend=backend,
        model=model_name,
        llm_stage=llm_stage,
        client=openrouter_client,
        max_tokens=max_tokens,
        reasoning=reasoning,
        progress=logger,
    )


def _openrouter_backend(
    prompts: list[PromptItem],
    *,
    requested_backend: str,
    model: str,
    llm_stage: str,
    client: OpenRouterClient,
    max_tokens: int | None,
    reasoning: dict[str, Any] | None,
    progress: ProgressLogger,
) -> BackendResult:
    llm_planner = OpenRouterPlannerAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    llm_generator = OpenRouterSvgGeneratorAgent(client, max_tokens=max_tokens, reasoning=reasoning)

    plans: list[IconPlan] = []
    artifacts: list[SvgArtifact] = []
    traces: list[BackendTrace] = []
    raw_events: list[dict[str, Any]] = []

    total = len(prompts)
    for index, item in enumerate(prompts, start=1):
        progress.log(f"[{index}/{total}] {item.id}: requesting LLM plan.")
        trace = BackendTrace(
            id=item.id,
            requested_backend=requested_backend,
            model=model,
            llm_stage=llm_stage,
        )

        try:
            plan_result = llm_planner.plan(item)
        except OpenRouterError as exc:
            trace.planner_backend = "openrouter-error"
            trace.errors.append(f"planner: {exc}")
            raw_events.append(_raw_event(item.id, "planner", "error", model, error=exc))
            traces.append(trace)
            progress.log(f"[{index}/{total}] {item.id}: LLM planner failed; no local fallback generated.")
            continue

        plan = plan_result.plan
        plans.append(plan)
        trace.planner_backend = "openrouter"
        trace.usage["planner"] = plan_result.response.usage
        raw_events.append(_raw_event(item.id, "planner", "success", model, response=plan_result.response.raw))
        progress.log(f"[{index}/{total}] {item.id}: LLM plan ready.")

        progress.log(f"[{index}/{total}] {item.id}: requesting LLM SVG draft.")
        try:
            svg_result = llm_generator.generate(plan)
        except OpenRouterError as exc:
            trace.svg_backend = "openrouter-error"
            trace.errors.append(f"svg: {exc}")
            raw_events.append(_raw_event(item.id, "svg", "error", model, error=exc))
            traces.append(trace)
            progress.log(f"[{index}/{total}] {item.id}: LLM SVG draft failed; no local fallback generated.")
            continue

        artifacts.append(svg_result.artifact)
        trace.svg_backend = "openrouter"
        trace.usage["svg"] = svg_result.response.usage
        raw_events.append(_raw_event(item.id, "svg", "success", model, response=svg_result.response.raw))
        traces.append(trace)
        progress.log(f"[{index}/{total}] {item.id}: baseline SVG draft ready.")

    return BackendResult(
        plans=plans,
        artifacts=artifacts,
        traces=traces,
        active_backend="openrouter",
        raw_llm_events=raw_events,
    )


def _raw_event(
    prompt_id: str,
    stage: str,
    status: str,
    model: str,
    *,
    response: dict[str, Any] | None = None,
    error: OpenRouterError | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": prompt_id,
        "stage": stage,
        "status": status,
        "model": model,
    }
    if response is not None:
        event["response"] = response
    if error is not None:
        event["error"] = str(error)
        event["debug_payload"] = error.debug_payload
    return event
