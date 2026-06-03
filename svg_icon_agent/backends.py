"""OpenRouter backend orchestration for LLM-backed icon generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from svg_icon_agent.llm_agents import (
    LlmCritiqueResult,
    ConsensusSelectorAgent,
    GoalManagerAgent,
    MultiCandidateGeneratorAgent,
    PlannerAgent,
    PromptRewriterAgent,
    SemanticCriticAgent,
    SvgGeneratorAgent,
    SvgOptimizerAgent,
    SvgQualityCriticAgent,
)
from svg_icon_agent.memory import MemoryContext
from svg_icon_agent.models import GenerationGoal, IconPlan, SvgArtifact, ValidationReport
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
    goal_manager_backend: str = "not-run"
    memory_curator_backend: str = "not-run"
    memory_enabled: bool = True
    memory_top_k: int = 3
    retrieved_memory_ids: list[str] = field(default_factory=list)
    optimizer_backend: str = "not-run"
    optimizer_applied: bool = False
    manual_optimizer_feedback: str | None = None
    use_llm_optimizer_feedback: bool = True
    optimizer_feedback_sources: list[str] = field(default_factory=list)
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
            "goal_manager_backend": self.goal_manager_backend,
            "memory_curator_backend": self.memory_curator_backend,
            "memory_enabled": self.memory_enabled,
            "memory_top_k": self.memory_top_k,
            "retrieved_memory_ids": self.retrieved_memory_ids,
            "optimizer_backend": self.optimizer_backend,
            "optimizer_applied": self.optimizer_applied,
            "manual_optimizer_feedback": self.manual_optimizer_feedback,
            "use_llm_optimizer_feedback": self.use_llm_optimizer_feedback,
            "optimizer_feedback_sources": self.optimizer_feedback_sources,
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
    goals: dict[str, GenerationGoal]
    plans: list[IconPlan]
    artifacts: list[SvgArtifact]
    candidate_artifacts: list[SvgArtifact]
    selected_artifacts: list[SvgArtifact]
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
    manual_goal: str | None = None,
    memory_contexts: dict[str, MemoryContext] | None = None,
    memory_enabled: bool = True,
    memory_top_k: int = 3,
    optimizer_feedback: str | None = None,
    use_llm_optimizer_feedback: bool = True,
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
        manual_goal=manual_goal,
        memory_contexts=memory_contexts or {},
        memory_enabled=memory_enabled,
        memory_top_k=memory_top_k,
        optimizer_feedback=optimizer_feedback,
        use_llm_optimizer_feedback=use_llm_optimizer_feedback,
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
    manual_goal: str | None,
    memory_contexts: dict[str, MemoryContext],
    memory_enabled: bool,
    memory_top_k: int,
    optimizer_feedback: str | None,
    use_llm_optimizer_feedback: bool,
    progress: ProgressLogger,
) -> BackendResult:
    goal_manager = GoalManagerAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    prompt_rewriter = PromptRewriterAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    llm_planner = PlannerAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    llm_generator = SvgGeneratorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    candidate_generator = MultiCandidateGeneratorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    semantic_critic = SemanticCriticAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    quality_critic = SvgQualityCriticAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    selector = ConsensusSelectorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    optimizer = SvgOptimizerAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    checker = SvgCheckTool()

    goals: dict[str, GenerationGoal] = {}
    plans: list[IconPlan] = []
    artifacts: list[SvgArtifact] = []
    candidate_artifacts: list[SvgArtifact] = []
    selected_artifacts: list[SvgArtifact] = []
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
            memory_enabled=memory_enabled,
            memory_top_k=memory_top_k,
            retrieved_memory_ids=memory_contexts.get(item.id).record_ids if memory_contexts.get(item.id) else [],
            original_prompt=item.prompt,
            rewritten_prompt=item.prompt,
            manual_optimizer_feedback=_clean_optional_text(optimizer_feedback),
            use_llm_optimizer_feedback=use_llm_optimizer_feedback,
        )

        memory_context = memory_contexts.get(item.id)
        progress.log(f"[{index}/{total}] {item.id}: requesting generation goal.")
        try:
            goal_result = goal_manager.create_goal(
                item,
                manual_goal=manual_goal,
                memory_context=memory_context,
            )
        except OpenRouterError as exc:
            trace.goal_manager_backend = "openrouter-error"
            trace.errors.append(f"goal-manager: {exc}")
            raw_events.append(_raw_event(item.id, "goal-manager", "error", model, error=exc))
            traces.append(trace)
            progress.log(f"[{index}/{total}] {item.id}: goal manager failed; no local fallback generated.")
            continue
        goal = goal_result.goal
        goals[item.id] = goal
        trace.goal_manager_backend = "openrouter"
        trace.usage["goal_manager"] = goal_result.response.usage
        raw_events.append(_raw_event(item.id, "goal-manager", "success", model, response=goal_result.response.raw))
        progress.log(f"[{index}/{total}] {item.id}: generation goal ready.")

        active_item = item
        if rewrite_prompt:
            progress.log(f"[{index}/{total}] {item.id}: requesting prompt rewrite.")
            try:
                rewrite_result = prompt_rewriter.rewrite(item, goal=goal, memory_context=memory_context)
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
            plan_result = llm_planner.plan(active_item, goal=goal, memory_context=memory_context)
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
                optimizer=optimizer,
                checker=checker,
                trace=trace,
                raw_events=raw_events,
                goal=goal,
                memory_context=memory_context,
                optimizer_feedback=optimizer_feedback,
                use_llm_optimizer_feedback=use_llm_optimizer_feedback,
                progress=progress,
            )
            if selected is None:
                traces.append(trace)
                continue
            artifact, repair_brief, candidates, selected_artifact = selected
            candidate_artifacts.extend(candidates)
            selected_artifacts.append(selected_artifact)
            artifacts.append(artifact)
            if repair_brief:
                selection_briefs[item.id] = repair_brief
        else:
            progress.log(f"[{index}/{total}] {item.id}: requesting LLM SVG draft.")
            try:
                svg_result = llm_generator.generate(plan, goal=goal, memory_context=memory_context)
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
        goals=goals,
        plans=plans,
        artifacts=artifacts,
        candidate_artifacts=candidate_artifacts,
        selected_artifacts=selected_artifacts,
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
    candidate_generator: MultiCandidateGeneratorAgent,
    semantic_critic: SemanticCriticAgent,
    quality_critic: SvgQualityCriticAgent,
    selector: ConsensusSelectorAgent,
    optimizer: SvgOptimizerAgent,
    checker: SvgCheckTool,
    trace: BackendTrace,
    raw_events: list[dict[str, Any]],
    goal: GenerationGoal,
    memory_context: MemoryContext | None,
    optimizer_feedback: str | None,
    use_llm_optimizer_feedback: bool,
    progress: ProgressLogger,
) -> tuple[SvgArtifact, str, list[SvgArtifact], SvgArtifact] | None:
    progress.log(f"[{index}/{total}] {plan.id}: requesting {candidate_count} LLM SVG candidates.")
    candidates: list[SvgArtifact] = []
    for candidate_index in range(1, candidate_count + 1):
        stage = f"candidate-{candidate_index}"
        try:
            result = candidate_generator.generate_one(
                plan,
                candidate_index=candidate_index,
                candidate_count=candidate_count,
                goal=goal,
                memory_context=memory_context,
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
    selected_artifact = SvgArtifact(id=plan.id, stage="selected", svg=winner.svg)
    winner_report = checker.check(winner)
    try:
        progress.log(f"[{index}/{total}] {plan.id}: requesting SVG optimizer.")
        optimized = optimizer.optimize(
            plan,
            selected_artifact,
            critiques,
            winner_report,
            selection,
            manual_feedback=optimizer_feedback,
            use_llm_feedback=use_llm_optimizer_feedback,
            goal=goal,
            memory_context=memory_context,
        )
        trace.optimizer_backend = "openrouter"
        trace.optimizer_applied = True
        trace.optimizer_feedback_sources = list(optimized.feedback_sources)
        trace.usage["optimizer"] = optimized.response.usage
        raw_events.append(
            _raw_event(
                plan.id,
                "svg-optimizer",
                "success",
                model,
                response=optimized.response.raw,
            )
        )
    except OpenRouterError as exc:
        trace.optimizer_backend = "openrouter-error"
        trace.errors.append(f"optimizer: {exc}")
        raw_events.append(_raw_event(plan.id, "svg-optimizer", "error", model, error=exc))
        progress.log(f"[{index}/{total}] {plan.id}: SVG optimizer failed; no local fallback generated.")
        return None
    progress.log(f"[{index}/{total}] {plan.id}: optimized baseline SVG ready.")
    return optimized.artifact, selection.repair_brief, candidates, selected_artifact


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


def _clean_optional_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None
