"""OpenRouter backend orchestration for LLM-backed icon generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from svg_icon_agent.llm_agents import (
    LlmCritiqueResult,
    OpenRouterConsensusSelectorAgent,
    OpenRouterMultiCandidateGeneratorAgent,
    OpenRouterPlannerAgent,
    OpenRouterPromptRewriterAgent,
    OpenRouterSemanticCriticAgent,
    OpenRouterSvgGeneratorAgent,
    OpenRouterSvgQualityCriticAgent,
)
from svg_icon_agent.models import IconPlan, SvgArtifact, ValidationReport
from svg_icon_agent.openrouter_client import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterClient,
    OpenRouterConfig,
    OpenRouterError,
)
from svg_icon_agent.progress import ProgressLogger
from svg_icon_agent.prompts import PromptItem
from svg_icon_agent.svg_check_tool import SvgCheckTool


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
    rewriter_backend: str = "not-run"
    original_prompt: str | None = None
    rewritten_prompt: str | None = None
    workflow: str = "single"
    candidate_count: int = 1
    selected_candidate_id: str | None = None
    selector_rationale: str | None = None
    selector_repair_brief: str | None = None
    candidate_tool_scores: dict[str, int] = field(default_factory=dict)
    critic_scores: dict[str, dict[str, int]] = field(default_factory=dict)
    critic_reports: dict[str, dict[str, Any]] = field(default_factory=dict)
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
            "rewriter_backend": self.rewriter_backend,
            "original_prompt": self.original_prompt,
            "rewritten_prompt": self.rewritten_prompt,
            "workflow": self.workflow,
            "candidate_count": self.candidate_count,
            "selected_candidate_id": self.selected_candidate_id,
            "selector_rationale": self.selector_rationale,
            "selector_repair_brief": self.selector_repair_brief,
            "candidate_tool_scores": self.candidate_tool_scores,
            "critic_scores": self.critic_scores,
            "critic_reports": self.critic_reports,
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
    candidate_artifacts: list[SvgArtifact]
    traces: list[BackendTrace]
    active_backend: str
    selection_briefs: dict[str, str] = field(default_factory=dict)
    raw_llm_events: list[dict[str, Any]] = field(default_factory=list)


def create_openrouter_client(
    *,
    model: str | None = None,
    request_timeout: float | None = None,
    max_retries: int | None = None,
    empty_response_retries: int | None = None,
) -> OpenRouterClient:
    return OpenRouterClient(
        OpenRouterConfig.from_env(
            model=model or DEFAULT_OPENROUTER_MODEL,
            timeout=request_timeout,
            max_retries=max_retries,
            empty_response_retries=empty_response_retries,
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
    empty_response_retries: int | None = None,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
    workflow: str = "single",
    candidate_count: int = 3,
    rewrite_prompt: bool = True,
    progress: ProgressLogger | None = None,
) -> BackendResult:
    if backend != "openrouter":
        raise ValueError("Only the OpenRouter backend is supported; local rule generation has been removed.")
    if llm_stage != "plan-svg":
        raise ValueError("Only llm_stage=plan-svg is supported because SVG generation must be model-backed.")
    if workflow not in {"single", "collaborative"}:
        raise ValueError("workflow must be single or collaborative.")
    if candidate_count < 1:
        raise ValueError("candidate_count must be at least 1.")

    model_name = model or DEFAULT_OPENROUTER_MODEL
    logger = progress or ProgressLogger(verbose=False)
    openrouter_client = client or create_openrouter_client(
        model=model_name,
        request_timeout=request_timeout,
        max_retries=max_retries,
        empty_response_retries=empty_response_retries,
    )

    timeout = getattr(getattr(openrouter_client, "config", None), "timeout", request_timeout)
    retries = getattr(getattr(openrouter_client, "config", None), "max_retries", max_retries)
    empty_retries = getattr(
        getattr(openrouter_client, "config", None),
        "empty_response_retries",
        empty_response_retries,
    )
    logger.log(
        f"Using OpenRouter backend for {len(prompts)} prompts "
        f"(timeout={timeout}s, retries={retries}, empty-response-retries={empty_retries})."
    )
    return _openrouter_backend(
        prompts,
        requested_backend=backend,
        model=model_name,
        llm_stage=llm_stage,
        client=openrouter_client,
        max_tokens=max_tokens,
        reasoning=reasoning,
        workflow=workflow,
        candidate_count=candidate_count,
        rewrite_prompt=rewrite_prompt,
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
    workflow: str,
    candidate_count: int,
    rewrite_prompt: bool,
    progress: ProgressLogger,
) -> BackendResult:
    prompt_rewriter = OpenRouterPromptRewriterAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    llm_planner = OpenRouterPlannerAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    llm_generator = OpenRouterSvgGeneratorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    candidate_generator = OpenRouterMultiCandidateGeneratorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    semantic_critic = OpenRouterSemanticCriticAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    quality_critic = OpenRouterSvgQualityCriticAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    selector = OpenRouterConsensusSelectorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    checker = SvgCheckTool()

    plans: list[IconPlan] = []
    artifacts: list[SvgArtifact] = []
    candidate_artifacts: list[SvgArtifact] = []
    traces: list[BackendTrace] = []
    selection_briefs: dict[str, str] = {}
    raw_events: list[dict[str, Any]] = []

    total = len(prompts)
    for index, item in enumerate(prompts, start=1):
        trace = BackendTrace(
            id=item.id,
            requested_backend=requested_backend,
            model=model,
            llm_stage=llm_stage,
            workflow=workflow,
            candidate_count=candidate_count if workflow == "collaborative" else 1,
            original_prompt=item.prompt,
            rewritten_prompt=item.prompt,
        )

        active_item = item
        if rewrite_prompt:
            progress.log(f"[{index}/{total}] {item.id}: requesting prompt rewrite.")
            try:
                rewrite_result = prompt_rewriter.rewrite(item)
            except OpenRouterError as exc:
                trace.rewriter_backend = "openrouter-error"
                trace.errors.append(f"rewriter: {exc}")
                raw_events.append(_raw_event(item.id, "prompt-rewriter", "error", model, error=exc))
                traces.append(trace)
                progress.log(f"[{index}/{total}] {item.id}: prompt rewriter failed; no local fallback generated.")
                continue
            active_item = rewrite_result.item
            trace.rewriter_backend = "openrouter"
            trace.rewritten_prompt = rewrite_result.rewritten_prompt
            trace.usage["prompt_rewriter"] = rewrite_result.response.usage
            progress.record_prompt_rewrite(item.id, item.prompt, rewrite_result.rewritten_prompt)
            raw_events.append(_raw_event(item.id, "prompt-rewriter", "success", model, response=rewrite_result.response.raw))
            progress.log(f"[{index}/{total}] {item.id}: rewritten prompt ready.")
        else:
            trace.rewriter_backend = "skipped"

        progress.log(f"[{index}/{total}] {item.id}: requesting LLM plan.")
        try:
            plan_result = llm_planner.plan(active_item)
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

        if workflow == "collaborative":
            selected = _collaborative_svg_draft(
                plan,
                index=index,
                total=total,
                candidate_count=candidate_count,
                model=model,
                candidate_generator=candidate_generator,
                semantic_critic=semantic_critic,
                quality_critic=quality_critic,
                selector=selector,
                checker=checker,
                trace=trace,
                raw_events=raw_events,
                progress=progress,
            )
            if selected is None:
                traces.append(trace)
                continue
            artifact, repair_brief, candidates = selected
            candidate_artifacts.extend(candidates)
            artifacts.append(artifact)
            if repair_brief:
                selection_briefs[item.id] = repair_brief
        else:
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
        candidate_artifacts=candidate_artifacts,
        traces=traces,
        active_backend="openrouter",
        selection_briefs=selection_briefs,
        raw_llm_events=raw_events,
    )


def _collaborative_svg_draft(
    plan: IconPlan,
    *,
    index: int,
    total: int,
    candidate_count: int,
    model: str,
    candidate_generator: OpenRouterMultiCandidateGeneratorAgent,
    semantic_critic: OpenRouterSemanticCriticAgent,
    quality_critic: OpenRouterSvgQualityCriticAgent,
    selector: OpenRouterConsensusSelectorAgent,
    checker: SvgCheckTool,
    trace: BackendTrace,
    raw_events: list[dict[str, Any]],
    progress: ProgressLogger,
) -> tuple[SvgArtifact, str, list[SvgArtifact]] | None:
    progress.log(f"[{index}/{total}] {plan.id}: requesting {candidate_count} LLM SVG candidates.")
    candidates: list[SvgArtifact] = []
    for candidate_index in range(1, candidate_count + 1):
        stage = f"candidate-{candidate_index}"
        try:
            result = candidate_generator.generate_one(
                plan,
                candidate_index=candidate_index,
                candidate_count=candidate_count,
            )
        except OpenRouterError as exc:
            trace.errors.append(f"{stage}: {exc}")
            raw_events.append(_raw_event(plan.id, "candidate-svg", "error", model, error=exc, candidate_id=stage))
            progress.log(f"[{index}/{total}] {plan.id}: {stage} failed; continuing with remaining candidates.")
            continue
        candidates.append(result.artifact)
        trace.usage[f"svg_{stage}"] = result.response.usage
        raw_events.append(
            _raw_event(plan.id, "candidate-svg", "success", model, response=result.response.raw, candidate_id=stage)
        )

    if not candidates:
        trace.svg_backend = "openrouter-error"
        trace.errors.append("svg: all collaborative candidates failed")
        progress.log(f"[{index}/{total}] {plan.id}: all LLM candidates failed; no local fallback generated.")
        return None

    tool_reports = [checker.check(candidate) for candidate in candidates]
    trace.candidate_count = len(candidates)
    trace.candidate_tool_scores = {candidate.stage: report.score for candidate, report in zip(candidates, tool_reports)}

    try:
        progress.log(f"[{index}/{total}] {plan.id}: requesting semantic critic.")
        semantic = semantic_critic.critique(plan, candidates)
        trace.usage["semantic_critic"] = semantic.response.usage
        raw_events.append(_raw_event(plan.id, "semantic-critic", "success", model, response=semantic.response.raw))

        progress.log(f"[{index}/{total}] {plan.id}: requesting SVG quality critic.")
        quality = quality_critic.critique(plan, candidates, tool_reports)
        trace.usage["svg_quality_critic"] = quality.response.usage
        raw_events.append(_raw_event(plan.id, "svg-quality-critic", "success", model, response=quality.response.raw))

        critiques = [semantic, quality]
        trace.critic_scores = _critic_scores(critiques)
        trace.critic_reports = _critic_reports(critiques)

        progress.log(f"[{index}/{total}] {plan.id}: requesting consensus selector.")
        selection = selector.select(plan, candidates, critiques, tool_reports)
        trace.usage["selector"] = selection.response.usage
        raw_events.append(_raw_event(plan.id, "selector", "success", model, response=selection.response.raw))
    except OpenRouterError as exc:
        trace.svg_backend = "openrouter-error"
        trace.errors.append(f"collaboration: {exc}")
        raw_events.append(_raw_event(plan.id, "collaboration", "error", model, error=exc))
        progress.log(f"[{index}/{total}] {plan.id}: collaborative review failed; no local fallback generated.")
        return None

    by_candidate_id = {candidate.stage: candidate for candidate in candidates}
    winner = by_candidate_id[selection.winner_candidate_id]
    trace.svg_backend = "openrouter-collaborative"
    trace.selected_candidate_id = selection.winner_candidate_id
    trace.selector_rationale = selection.rationale
    trace.selector_repair_brief = selection.repair_brief
    progress.log(f"[{index}/{total}] {plan.id}: selector chose {selection.winner_candidate_id}.")
    return SvgArtifact(id=plan.id, stage="baseline", svg=winner.svg), selection.repair_brief, candidates


def _critic_scores(critiques: list[LlmCritiqueResult]) -> dict[str, dict[str, int]]:
    return {
        result.perspective: {
            critique.candidate_id: critique.score
            for critique in result.critiques
        }
        for result in critiques
    }


def _critic_reports(critiques: list[LlmCritiqueResult]) -> dict[str, dict[str, Any]]:
    return {
        result.perspective: {
            critique.candidate_id: critique.to_json()
            for critique in result.critiques
        }
        for result in critiques
    }


def _raw_event(
    prompt_id: str,
    stage: str,
    status: str,
    model: str,
    *,
    response: dict[str, Any] | None = None,
    error: OpenRouterError | None = None,
    candidate_id: str | None = None,
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
    if candidate_id is not None:
        event["candidate_id"] = candidate_id
    return event
