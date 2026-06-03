"""OpenRouter-backed agents for the SVG icon pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from svg_icon_agent.memory import MemoryContext
from svg_icon_agent.models import (
    FailureTaxonomy,
    GenerationGoal,
    IconPlan,
    RepairRoute,
    SvgArtifact,
    ValidationIssue,
    ValidationReport,
)
from svg_icon_agent.openrouter_client import OpenRouterClient, OpenRouterError, OpenRouterResponse
from svg_icon_agent.prompts import HEX_RE, PromptItem, VALID_CATEGORIES, VALID_STYLES

DEFAULT_PLANNER_MAX_TOKENS = 900
DEFAULT_GOAL_MAX_TOKENS = 900
DEFAULT_MEMORY_CURATOR_MAX_TOKENS = 900
DEFAULT_REWRITER_MAX_TOKENS = 700
DEFAULT_SVG_MAX_TOKENS = 1800
DEFAULT_VALIDATOR_MAX_TOKENS = 1200
DEFAULT_FAILURE_TAXONOMY_MAX_TOKENS = 1200
DEFAULT_REPAIR_ROUTER_MAX_TOKENS = 1200
DEFAULT_OPTIMIZER_MAX_TOKENS = 2200
DEFAULT_REFINER_MAX_TOKENS = 2200


@dataclass(frozen=True)
class LlmRewriteResult:
    item: PromptItem
    rewritten_prompt: str
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmGoalResult:
    goal: GenerationGoal
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmMemoryCuratorResult:
    record: dict[str, Any]
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmPlanResult:
    plan: IconPlan
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmSvgResult:
    artifact: SvgArtifact
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmValidationResult:
    report: ValidationReport
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmFailureTaxonomyResult:
    taxonomy: FailureTaxonomy
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmRepairRouteResult:
    route: RepairRoute
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmRefinementResult:
    artifact: SvgArtifact
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmOptimizationResult:
    artifact: SvgArtifact
    response: OpenRouterResponse
    feedback_sources: tuple[str, ...]


@dataclass(frozen=True)
class CandidateCritique:
    candidate_id: str
    score: int
    strengths: tuple[str, ...]
    issues: tuple[str, ...]
    recommendation: str

    def to_json(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "score": self.score,
            "strengths": list(self.strengths),
            "issues": list(self.issues),
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class LlmCandidateBatchResult:
    artifacts: tuple[SvgArtifact, ...]
    responses: tuple[OpenRouterResponse, ...]


@dataclass(frozen=True)
class LlmCritiqueResult:
    perspective: str
    critiques: tuple[CandidateCritique, ...]
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmSelectionResult:
    winner_candidate_id: str
    rationale: str
    risks: tuple[str, ...]
    repair_brief: str
    response: OpenRouterResponse

    def to_json(self) -> dict[str, Any]:
        return {
            "winner_candidate_id": self.winner_candidate_id,
            "rationale": self.rationale,
            "risks": list(self.risks),
            "repair_brief": self.repair_brief,
        }


class PromptRewriterAgent:
    """Uses an OpenRouter model to rewrite a user prompt for SVG icon generation."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def rewrite(
        self,
        item: PromptItem,
        *,
        goal: GenerationGoal | None = None,
        memory_context: MemoryContext | None = None,
    ) -> LlmRewriteResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a prompt rewriting agent for editable SVG icon generation. "
                        "Return only JSON. Do not specify exact colors unless the user explicitly asked for them."
                    ),
                },
                {
                    "role": "user",
                    "content": _rewrite_prompt(item, goal=goal, memory_context=memory_context),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.15,
            max_tokens=self.max_tokens or DEFAULT_REWRITER_MAX_TOKENS,
        )
        data = _json_object(response.content, "Prompt rewriter")
        rewritten = _coerce_rewritten_prompt(item, data)
        rewritten_item = PromptItem(
            id=item.id,
            category=item.category,
            prompt=rewritten,
            style=item.style,
            palette=item.palette,
            source=item.source,
        )
        return LlmRewriteResult(item=rewritten_item, rewritten_prompt=rewritten, response=response)


class GoalManagerAgent:
    """Uses an OpenRouter model to turn prompt, manual goal, and memories into a generation goal."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def create_goal(
        self,
        item: PromptItem,
        *,
        manual_goal: str | None = None,
        memory_context: MemoryContext | None = None,
    ) -> LlmGoalResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a goal manager agent for SVG icon generation. Return only JSON. "
                        "Convert the user request into concrete visual goals, constraints, acceptance criteria, "
                        "style preferences, and avoid patterns."
                    ),
                },
                {
                    "role": "user",
                    "content": _goal_prompt(item, manual_goal=manual_goal, memory_context=memory_context),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.12,
            max_tokens=self.max_tokens or DEFAULT_GOAL_MAX_TOKENS,
        )
        return LlmGoalResult(
            goal=_coerce_goal(item, _json_object(response.content, "Goal manager"), manual_goal=manual_goal),
            response=response,
        )


class PlannerAgent:
    """Uses an OpenRouter model to produce an IconPlan-compatible JSON object."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def plan(
        self,
        item: PromptItem,
        *,
        goal: GenerationGoal | None = None,
        memory_context: MemoryContext | None = None,
    ) -> LlmPlanResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a precise icon planning agent. Return only JSON. "
                        "Do not include markdown. Keep values compact and useful for SVG generation."
                    ),
                },
                {
                    "role": "user",
                    "content": _plan_prompt(item, goal=goal, memory_context=memory_context),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.2,
            max_tokens=self.max_tokens or DEFAULT_PLANNER_MAX_TOKENS,
        )
        data = _json_object(response.content, "Planner")
        return LlmPlanResult(plan=_coerce_plan(item, data), response=response)


class SvgGeneratorAgent:
    """Uses an OpenRouter model to draft a safe, compact SVG icon."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def generate(
        self,
        plan: IconPlan,
        stage: str = "baseline",
        *,
        goal: GenerationGoal | None = None,
        memory_context: MemoryContext | None = None,
    ) -> LlmSvgResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You generate safe SVG icons. Return only one SVG document. "
                        "Do not include markdown, explanations, scripts, images, external assets, CSS, or animations."
                    ),
                },
                {
                    "role": "user",
                    "content": _svg_prompt(plan, goal=goal, memory_context=memory_context),
                },
            ],
            reasoning=self.reasoning,
            temperature=0.25,
            max_tokens=self.max_tokens or DEFAULT_SVG_MAX_TOKENS,
        )
        return LlmSvgResult(
            artifact=SvgArtifact(id=plan.id, stage=stage, svg=_extract_svg(response.content)),
            response=response,
        )


class MultiCandidateGeneratorAgent:
    """Uses an OpenRouter model to draft several deliberately different SVG candidates."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def generate(self, plan: IconPlan, candidate_count: int = 3) -> LlmCandidateBatchResult:
        artifacts: list[SvgArtifact] = []
        responses: list[OpenRouterResponse] = []
        for index in range(1, candidate_count + 1):
            result = self.generate_one(plan, candidate_index=index, candidate_count=candidate_count)
            artifacts.append(result.artifact)
            responses.append(result.response)
        return LlmCandidateBatchResult(artifacts=tuple(artifacts), responses=tuple(responses))

    def generate_one(
        self,
        plan: IconPlan,
        *,
        candidate_index: int,
        candidate_count: int,
        goal: GenerationGoal | None = None,
        memory_context: MemoryContext | None = None,
    ) -> LlmSvgResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You generate safe SVG icon candidates. Return only one SVG document. "
                        "Do not include markdown, explanations, scripts, images, external assets, CSS, or animations."
                    ),
                },
                {
                    "role": "user",
                    "content": _candidate_svg_prompt(
                        plan,
                        candidate_index,
                        candidate_count,
                        goal=goal,
                        memory_context=memory_context,
                    ),
                },
            ],
            reasoning=self.reasoning,
            temperature=0.35,
            max_tokens=self.max_tokens or DEFAULT_SVG_MAX_TOKENS,
        )
        return LlmSvgResult(
            artifact=SvgArtifact(id=plan.id, stage=f"candidate-{candidate_index}", svg=_extract_svg(response.content)),
            response=response,
        )


class ValidatorAgent:
    """Uses an OpenRouter model to judge SVG semantics, aesthetics, and rule fit."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def validate(
        self,
        plan: IconPlan,
        artifact: SvgArtifact,
        tool_report: ValidationReport,
        *,
        round_index: int = 0,
    ) -> LlmValidationResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an SVG icon validator agent. Return only JSON. "
                        "Judge semantic alignment, visual clarity, editability, and safety. "
                        "Treat the deterministic tool report as evidence, but make your own concise judgment."
                    ),
                },
                {
                    "role": "user",
                    "content": _validation_prompt(plan, artifact, tool_report, round_index),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.1,
            max_tokens=self.max_tokens or DEFAULT_VALIDATOR_MAX_TOKENS,
        )
        data = _json_object(response.content, "Validator")
        return LlmValidationResult(
            report=_coerce_validation_report(artifact, data, tool_report),
            response=response,
        )


class FailureTaxonomyAgent:
    """Uses a model to classify validation failures before repair."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def classify(
        self,
        plan: IconPlan,
        artifact: SvgArtifact,
        validation_report: ValidationReport,
        tool_report: ValidationReport,
        *,
        round_index: int,
    ) -> LlmFailureTaxonomyResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a failure taxonomy agent for SVG icon repair. Return only JSON. "
                        "Classify the actual repair blockers, cite evidence, and keep the output concise."
                    ),
                },
                {
                    "role": "user",
                    "content": _failure_taxonomy_prompt(
                        plan,
                        artifact,
                        validation_report,
                        tool_report,
                        round_index,
                    ),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.08,
            max_tokens=self.max_tokens or DEFAULT_FAILURE_TAXONOMY_MAX_TOKENS,
        )
        data = _json_object(response.content, "Failure taxonomy")
        return LlmFailureTaxonomyResult(
            taxonomy=_coerce_failure_taxonomy(artifact, data, round_index),
            response=response,
        )


class RepairRouterAgent:
    """Uses a model to choose a repair strategy for the Refiner Agent."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def route(
        self,
        plan: IconPlan,
        artifact: SvgArtifact,
        validation_report: ValidationReport,
        tool_report: ValidationReport,
        taxonomy: FailureTaxonomy,
        *,
        round_index: int,
        collaboration_brief: str | None = None,
    ) -> LlmRepairRouteResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a repair router agent for SVG icon repair. Return only JSON. "
                        "Choose one repair route and write a brief that another model can use to repair the SVG."
                    ),
                },
                {
                    "role": "user",
                    "content": _repair_router_prompt(
                        plan,
                        artifact,
                        validation_report,
                        tool_report,
                        taxonomy,
                        round_index,
                        collaboration_brief=collaboration_brief,
                    ),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.08,
            max_tokens=self.max_tokens or DEFAULT_REPAIR_ROUTER_MAX_TOKENS,
        )
        data = _json_object(response.content, "Repair router")
        return LlmRepairRouteResult(
            route=_coerce_repair_route(artifact, data, round_index),
            response=response,
        )


class SemanticCriticAgent:
    """Uses an OpenRouter model to judge prompt alignment and small-icon readability."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def critique(self, plan: IconPlan, candidates: list[SvgArtifact]) -> LlmCritiqueResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a semantic SVG icon critic. Return only JSON. "
                        "Judge whether each candidate clearly communicates the prompt at small icon size."
                    ),
                },
                {"role": "user", "content": _semantic_critique_prompt(plan, candidates)},
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.1,
            max_tokens=self.max_tokens or DEFAULT_VALIDATOR_MAX_TOKENS,
        )
        return LlmCritiqueResult(
            perspective="semantic",
            critiques=_coerce_critiques(_json_object(response.content, "Semantic critic"), candidates),
            response=response,
        )


class SvgQualityCriticAgent:
    """Uses an OpenRouter model to judge SVG editability, safety, and rendering risk."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def critique(
        self,
        plan: IconPlan,
        candidates: list[SvgArtifact],
        tool_reports: list[ValidationReport],
    ) -> LlmCritiqueResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an SVG quality critic. Return only JSON. "
                        "Judge editability, primitive simplicity, safety, and rendering risk."
                    ),
                },
                {"role": "user", "content": _quality_critique_prompt(plan, candidates, tool_reports)},
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.1,
            max_tokens=self.max_tokens or DEFAULT_VALIDATOR_MAX_TOKENS,
        )
        return LlmCritiqueResult(
            perspective="svg-quality",
            critiques=_coerce_critiques(_json_object(response.content, "SVG quality critic"), candidates),
            response=response,
        )


class ConsensusSelectorAgent:
    """Uses an OpenRouter model to choose the best candidate from critic reports."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def select(
        self,
        plan: IconPlan,
        candidates: list[SvgArtifact],
        critiques: list[LlmCritiqueResult],
        tool_reports: list[ValidationReport],
    ) -> LlmSelectionResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a consensus selector for an SVG icon agent team. Return only JSON. "
                        "Choose one candidate and explain the choice concisely."
                    ),
                },
                {"role": "user", "content": _selection_prompt(plan, candidates, critiques, tool_reports)},
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.1,
            max_tokens=self.max_tokens or DEFAULT_VALIDATOR_MAX_TOKENS,
        )
        data = _json_object(response.content, "Consensus selector")
        return _coerce_selection(data, candidates, response)


class SvgOptimizerAgent:
    """Uses an OpenRouter model to optimize the selected SVG from agent feedback."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def optimize(
        self,
        plan: IconPlan,
        selected_artifact: SvgArtifact,
        critiques: list[LlmCritiqueResult],
        tool_report: ValidationReport,
        selection: LlmSelectionResult,
        *,
        manual_feedback: str | None = None,
        use_llm_feedback: bool = True,
        goal: GenerationGoal | None = None,
        memory_context: MemoryContext | None = None,
    ) -> LlmOptimizationResult:
        feedback_sources = _optimizer_feedback_sources(manual_feedback, use_llm_feedback)
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an SVG optimizer agent in a collaborative icon-generation team. "
                        "Return only one complete SVG document. Do not include markdown, explanations, scripts, "
                        "images, external assets, CSS, transforms, filters, gradients, text, or animations."
                    ),
                },
                {
                    "role": "user",
                    "content": _optimization_prompt(
                        plan,
                        selected_artifact,
                        critiques,
                        tool_report,
                        selection,
                        manual_feedback=manual_feedback,
                        use_llm_feedback=use_llm_feedback,
                        goal=goal,
                        memory_context=memory_context,
                    ),
                },
            ],
            reasoning=self.reasoning,
            temperature=0.18,
            max_tokens=self.max_tokens or DEFAULT_OPTIMIZER_MAX_TOKENS,
        )
        return LlmOptimizationResult(
            artifact=SvgArtifact(id=plan.id, stage="baseline", svg=_extract_svg(response.content)),
            response=response,
            feedback_sources=feedback_sources,
        )


class MemoryCuratorAgent:
    """Uses an OpenRouter model to summarize a completed run into a reusable memory record."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def curate(
        self,
        item: PromptItem,
        plan: IconPlan,
        *,
        goal: GenerationGoal | None,
        trace: dict[str, Any],
        metrics: dict[str, Any],
        memory_context: MemoryContext | None = None,
    ) -> LlmMemoryCuratorResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a memory curator agent for an SVG icon generation system. Return only JSON. "
                        "Create a short reusable memory that helps future similar icon generations."
                    ),
                },
                {
                    "role": "user",
                    "content": _memory_curator_prompt(item, plan, goal, trace, metrics, memory_context),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.12,
            max_tokens=self.max_tokens or DEFAULT_MEMORY_CURATOR_MAX_TOKENS,
        )
        return LlmMemoryCuratorResult(
            record=_coerce_memory_record(_json_object(response.content, "Memory curator")),
            response=response,
        )


class RefinerAgent:
    """Uses an OpenRouter model to return a repaired complete SVG document."""

    def __init__(
        self,
        client: OpenRouterClient,
        max_tokens: int | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.max_tokens = max_tokens
        self.reasoning = reasoning

    def refine(
        self,
        plan: IconPlan,
        artifact: SvgArtifact,
        validation_report: ValidationReport,
        tool_report: ValidationReport,
        *,
        round_index: int,
        collaboration_brief: str | None = None,
        repair_route: RepairRoute | None = None,
    ) -> LlmRefinementResult:
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an SVG repair agent. Return only one complete SVG document. "
                        "Do not include markdown, explanations, scripts, images, external assets, CSS, or animations."
                    ),
                },
                {
                    "role": "user",
                    "content": _refinement_prompt(
                        plan,
                        artifact,
                        validation_report,
                        tool_report,
                        round_index,
                        collaboration_brief=collaboration_brief,
                        repair_route=repair_route,
                    ),
                },
            ],
            reasoning=self.reasoning,
            temperature=0.2,
            max_tokens=self.max_tokens or DEFAULT_REFINER_MAX_TOKENS,
        )
        return LlmRefinementResult(
            artifact=SvgArtifact(id=artifact.id, stage="refined", svg=_extract_svg(response.content)),
            response=response,
        )


def _goal_prompt(
    item: PromptItem,
    *,
    manual_goal: str | None,
    memory_context: MemoryContext | None,
) -> str:
    manual_context = manual_goal.strip() if isinstance(manual_goal, str) and manual_goal.strip() else "No manual goal supplied."
    return f"""Create a structured SVG icon generation goal.
Return one JSON object with this exact shape:
{{
  "objective": "one concise sentence",
  "visual_requirements": ["short requirement"],
  "constraints": ["short constraint"],
  "acceptance_criteria": ["short criterion"],
  "style_preferences": ["short preference"],
  "avoid_patterns": ["short avoid pattern"]
}}

Rules:
- The goal is for a 256x256 editable SVG icon.
- Preserve the user's original intent.
- Use retrieved memories only as guidance; do not copy old SVG code.
- Make acceptance criteria concrete enough for later Agent evaluation.
- Do not include markdown or SVG code.

Original prompt:
{item.prompt}

Manual goal:
{manual_context}

Category hint: {item.category}
Style hint: {item.style}

Retrieved memory context:
{_memory_context_text(memory_context)}
"""


def _rewrite_prompt(
    item: PromptItem,
    *,
    goal: GenerationGoal | None = None,
    memory_context: MemoryContext | None = None,
) -> str:
    return f"""Rewrite and enrich this icon request for a text-to-SVG icon agent.
Return one JSON object with this exact shape:
{{
  "rewritten_prompt": "one polished English prompt, 35 to 60 words"
}}

Rules:
- Preserve the user's original intent and any explicitly requested subject, action, style, or color words.
- Expand vague input into a concrete 256x256 editable SVG icon brief.
- Add useful visual details: main subject, secondary motifs, silhouette, composition, visual hierarchy, and small-size readability.
- Mention simple geometric shapes or icon-friendly parts when helpful, without writing SVG code.
- Make the rewritten prompt noticeably richer than the original; do not merely paraphrase it.
- Do not add exact color names, color adjectives, or color hex values unless the original prompt explicitly included them.
- Do not contradict the category or style hints.
- Do not include SVG code, markdown, explanations, or multiple alternatives.

Original prompt:
{item.prompt}

Category hint: {item.category}
Style hint: {item.style}

Generation goal JSON:
{_goal_json_text(goal)}

Retrieved memory context:
{_memory_context_text(memory_context)}
"""


def _plan_prompt(
    item: PromptItem,
    *,
    goal: GenerationGoal | None = None,
    memory_context: MemoryContext | None = None,
) -> str:
    return f"""Create a JSON object for a 256x256 SVG icon plan.
Required keys:
- category: one of ui, object, scene
- style: one of line, filled, mixed
- palette: exactly three model-chosen #RRGGBB colors
- motifs: 2 to 6 short lowercase motif tokens
- layout: short layout name
- constraints: 4 to 8 short lowercase constraint tokens

Use this input as the source of truth:
id: {item.id}
category hint: {item.category}
style hint: {item.style}
prompt: {item.prompt}

Generation goal JSON:
{_goal_json_text(goal)}

Retrieved memory context:
{_memory_context_text(memory_context)}
"""


def _svg_prompt(
    plan: IconPlan,
    *,
    goal: GenerationGoal | None = None,
    memory_context: MemoryContext | None = None,
) -> str:
    motifs = ", ".join(plan.motifs)
    constraints = ", ".join(plan.constraints)
    return f"""Generate one complete SVG for this icon plan.
Hard requirements:
- Canvas must be exactly <svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">.
- Include <title> and <desc>.
- Use only these SVG elements: svg, title, desc, path, circle, rect, line, polyline, polygon, ellipse.
- Use only literal #RRGGBB colors plus white, black, none, or transparent.
- Do not use style attributes, classes, defs, filters, gradients, transforms, text, script, image, foreignObject, animation, or external references.
- Keep the icon readable at small size with 4 to 20 drawing primitives.

Icon id: {plan.id}
Prompt: {plan.prompt}
Category: {plan.category}
Style: {plan.style}
Motifs: {motifs}
Layout: {plan.layout}
Constraints: {constraints}

Generation goal JSON:
{_goal_json_text(goal)}

Retrieved memory context:
{_memory_context_text(memory_context)}
"""


def _candidate_svg_prompt(
    plan: IconPlan,
    candidate_index: int,
    candidate_count: int,
    *,
    goal: GenerationGoal | None = None,
    memory_context: MemoryContext | None = None,
) -> str:
    motifs = ", ".join(plan.motifs)
    constraints = ", ".join(plan.constraints)
    return f"""Generate candidate {candidate_index} of {candidate_count} for this icon plan.
Hard requirements:
- Canvas must be exactly <svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">.
- Include <title> and <desc>.
- Use only these SVG elements: svg, title, desc, path, circle, rect, line, polyline, polygon, ellipse.
- Use only literal #RRGGBB colors plus white, black, none, or transparent.
- Do not use style attributes, classes, defs, filters, gradients, transforms, text, script, image, foreignObject, animation, or external references.
- Keep the icon readable at small size with 4 to 20 drawing primitives.
- Make this candidate visibly different from the other candidates in layout, motif emphasis, or silhouette.
- Do not mention or expose candidate numbering inside title or desc.

Icon id: {plan.id}
Prompt: {plan.prompt}
Category: {plan.category}
Style: {plan.style}
Motifs: {motifs}
Layout: {plan.layout}
Constraints: {constraints}

Generation goal JSON:
{_goal_json_text(goal)}

Retrieved memory context:
{_memory_context_text(memory_context)}
"""


def _semantic_critique_prompt(plan: IconPlan, candidates: list[SvgArtifact]) -> str:
    return f"""Compare these SVG candidates for prompt alignment and icon recognizability.
Return one JSON object with this shape:
{{
  "critiques": [
    {{
      "candidate_id": "candidate-1",
      "score": integer from 0 to 100,
      "strengths": ["short phrase"],
      "issues": ["short phrase"],
      "recommendation": "short sentence"
    }}
  ]
}}

Judge only semantic clarity:
- Does it communicate "{plan.prompt}"?
- Is the main symbol recognizable at 24px to 32px?
- Does it preserve the planned motifs: {", ".join(plan.motifs)}?
- Penalize decorative complexity that makes the meaning unclear.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

Candidates:
{_candidate_svg_listing(candidates)}
"""


def _quality_critique_prompt(
    plan: IconPlan,
    candidates: list[SvgArtifact],
    tool_reports: list[ValidationReport],
) -> str:
    return f"""Compare these SVG candidates for vector quality and implementation safety.
Return one JSON object with this shape:
{{
  "critiques": [
    {{
      "candidate_id": "candidate-1",
      "score": integer from 0 to 100,
      "strengths": ["short phrase"],
      "issues": ["short phrase"],
      "recommendation": "short sentence"
    }}
  ]
}}

Judge only SVG quality:
- Safe editable SVG primitives only.
- Correct 256x256 canvas and viewBox.
- No scripts, external references, CSS, filters, gradients, images, text, or animation.
- Simple enough to edit and render reliably.
- Prefer candidates with fewer local tool issues.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

Deterministic tool reports JSON:
{json.dumps([report.to_json() for report in tool_reports], indent=2)}

Candidates:
{_candidate_svg_listing(candidates)}
"""


def _selection_prompt(
    plan: IconPlan,
    candidates: list[SvgArtifact],
    critiques: list[LlmCritiqueResult],
    tool_reports: list[ValidationReport],
) -> str:
    return f"""Select the best SVG candidate for final refinement.
Return one JSON object with this shape:
{{
  "winner_candidate_id": "candidate-1",
  "rationale": "one concise sentence",
  "risks": ["short risk or limitation"],
  "repair_brief": "one concise instruction for the refiner"
}}

Selection rules:
- Prefer a candidate that is both semantically clear and safe/editable.
- Use the critic reports and deterministic tool reports as evidence.
- Do not invent a new SVG. Choose exactly one listed candidate_id.
- The selected candidate will be refined by another LLM Agent.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

Critic reports JSON:
{json.dumps([_critique_result_json(result) for result in critiques], indent=2)}

Deterministic tool reports JSON:
{json.dumps([report.to_json() for report in tool_reports], indent=2)}

Candidates:
{_candidate_svg_listing(candidates)}
"""


def _optimization_prompt(
    plan: IconPlan,
    selected_artifact: SvgArtifact,
    critiques: list[LlmCritiqueResult],
    tool_report: ValidationReport,
    selection: LlmSelectionResult,
    *,
    manual_feedback: str | None,
    use_llm_feedback: bool,
    goal: GenerationGoal | None = None,
    memory_context: MemoryContext | None = None,
) -> str:
    manual = manual_feedback.strip() if isinstance(manual_feedback, str) else ""
    llm_context = ""
    if use_llm_feedback:
        llm_context = f"""
LLM critic reports JSON:
{json.dumps([_critique_result_json(result) for result in critiques], indent=2)}

Consensus selector JSON:
{json.dumps(selection.to_json(), indent=2)}
"""
    else:
        llm_context = "\nLLM critic and selector feedback: disabled by user option.\n"

    manual_context = manual if manual else "No manual optimizer feedback supplied."
    return f"""Improve the selected SVG before final validation/refinement.
Return only one complete SVG document.

Hard requirements:
- Canvas must be exactly <svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">.
- Include <title> and <desc>.
- Use only these SVG elements: svg, title, desc, path, circle, rect, line, polyline, polygon, ellipse.
- Use only literal #RRGGBB colors plus white, black, none, or transparent.
- Do not use style attributes, classes, defs, filters, gradients, transforms, text, script, image, foreignObject, animation, or external references.
- Keep 4 to 20 drawing primitives.
- Preserve the selected candidate's core silhouette and prompt semantics.
- Apply manual feedback when it is supplied.
- When LLM feedback is enabled, address the critic issues, selector risks, repair brief, and deterministic SVG check problems.
- When LLM feedback is disabled, do not use critic or selector advice; rely only on the selected SVG, the icon plan, the deterministic SVG check, and manual feedback.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

Generation goal JSON:
{_goal_json_text(goal)}

Retrieved memory context:
{_memory_context_text(memory_context)}

Manual optimizer feedback:
{manual_context}
{llm_context}
Deterministic SvgCheckTool report JSON:
{json.dumps(tool_report.to_json(), indent=2)}

Selected SVG to optimize:
{selected_artifact.svg}
"""


def _memory_curator_prompt(
    item: PromptItem,
    plan: IconPlan,
    goal: GenerationGoal | None,
    trace: dict[str, Any],
    metrics: dict[str, Any],
    memory_context: MemoryContext | None,
) -> str:
    return f"""Summarize this completed SVG icon run into a reusable memory record.
Return one JSON object with this exact shape:
{{
  "summary": "one concise reusable lesson",
  "success_patterns": ["short reusable design strategy"],
  "failure_patterns": ["short failure or risk to avoid"],
  "user_feedback": ["short user preference or manual advice"],
  "score": integer from 0 to 100,
  "tags": ["short lowercase tag"]
}}

Rules:
- Keep it short and useful for future similar icon generations.
- Do not include API keys, raw private payloads, full SVG code, or long model responses.
- Prefer design lessons, avoid patterns, and user feedback over implementation logs.

Prompt item JSON:
{json.dumps(item.__dict__, indent=2)}

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

Generation goal JSON:
{_goal_json_text(goal)}

Trace JSON excerpt:
{json.dumps(_trim_trace(trace), indent=2)}

Metrics JSON:
{json.dumps(metrics, indent=2)}

Previously retrieved memories:
{_memory_context_text(memory_context)}
"""


def _optimizer_feedback_sources(manual_feedback: str | None, use_llm_feedback: bool) -> tuple[str, ...]:
    sources = ["svg_check_tool"]
    if use_llm_feedback:
        sources.extend(["semantic_critic", "svg_quality_critic", "consensus_selector"])
    if isinstance(manual_feedback, str) and manual_feedback.strip():
        sources.append("manual_feedback")
    return tuple(sources)


def _candidate_svg_listing(candidates: list[SvgArtifact]) -> str:
    return "\n\n".join(f"Candidate id: {candidate.stage}\n{candidate.svg}" for candidate in candidates)


def _critique_result_json(result: LlmCritiqueResult) -> dict[str, Any]:
    return {
        "perspective": result.perspective,
        "critiques": [critique.to_json() for critique in result.critiques],
    }


def _validation_prompt(
    plan: IconPlan,
    artifact: SvgArtifact,
    tool_report: ValidationReport,
    round_index: int,
) -> str:
    return f"""Validate this SVG icon and return one JSON object.
Required JSON shape:
{{
  "valid": true or false,
  "score": integer from 0 to 100,
  "issues": [
    {{"code": "short-kebab-code", "severity": "error|warning|info", "message": "specific concise issue"}}
  ],
  "semantic_alignment": "one short sentence",
  "aesthetic_notes": "one short sentence",
  "repair_brief": "one short sentence for the refiner"
}}

Validation standards:
- The SVG must be a safe editable icon for prompt "{plan.prompt}".
- It should follow the planned motifs: {", ".join(plan.motifs)}.
- It must remain a 256x256 SVG with viewBox 0 0 256 256.
- It must avoid scripts, external references, raster images, animations, CSS, filters, gradients, and text elements.
- It should use only basic vector primitives and literal safe colors.
- Mark parse errors, unsafe tags, missing viewBox, missing title/desc, external references, invalid colors, and non-icon complexity as issues.
- Use severity "error" for unsafe or non-renderable problems.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

Deterministic SVG check report JSON:
{json.dumps(tool_report.to_json(), indent=2)}

Round index: {round_index}

SVG to validate:
{artifact.svg}
"""


def _failure_taxonomy_prompt(
    plan: IconPlan,
    artifact: SvgArtifact,
    validation_report: ValidationReport,
    tool_report: ValidationReport,
    round_index: int,
) -> str:
    return f"""Classify the failures that block this SVG icon from being accepted.
Return one JSON object with this exact shape:
{{
  "failure_types": ["syntax_safety|renderability|semantic_mismatch|visual_clarity|editability|constraint_violation"],
  "root_causes": ["short root cause"],
  "evidence": ["short evidence from validator, tool report, or SVG"],
  "priority": "low|medium|high|critical",
  "repair_goals": ["short repair goal"]
}}

Rules:
- Use only the listed failure type labels when they apply.
- Prefer specific evidence over generic advice.
- Focus on problems that a later SVG repair agent can actually fix.
- Do not propose local code changes, model settings, or prompt changes.
- Do not include markdown or SVG code.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}

LLM validator report JSON:
{json.dumps(validation_report.to_json(), indent=2)}

Deterministic SvgCheckTool report JSON:
{json.dumps(tool_report.to_json(), indent=2)}

Round index: {round_index}

Current SVG:
{artifact.svg}
"""


def _repair_router_prompt(
    plan: IconPlan,
    artifact: SvgArtifact,
    validation_report: ValidationReport,
    tool_report: ValidationReport,
    taxonomy: FailureTaxonomy,
    round_index: int,
    collaboration_brief: str | None = None,
) -> str:
    selector_context = (
        f"\nCollaborative selector repair brief:\n{collaboration_brief}\n"
        if collaboration_brief
        else "\nCollaborative selector repair brief: none.\n"
    )
    return f"""Choose the best repair route for the next SVG repair agent.
Return one JSON object with this exact shape:
{{
  "route": "safety_rebuild|semantic_recompose|simplify_icon|layout_rebalance|minor_patch",
  "strategy": "one concise repair strategy",
  "ordered_actions": ["imperative action for the refiner"],
  "refiner_brief": "one concise paragraph for the refiner",
  "risk_notes": ["short risk note"]
}}

Route meanings:
- safety_rebuild: unsafe, invalid, or non-renderable SVG must be rebuilt with allowed primitives.
- semantic_recompose: SVG is safe but does not express the requested icon.
- simplify_icon: SVG is too complex or unreadable at icon size.
- layout_rebalance: composition, centering, scale, or visual hierarchy needs repair.
- minor_patch: small localized fixes should preserve most of the current SVG.

Rules:
- Use taxonomy, validator issues, tool findings, and selector brief as evidence.
- Make ordered_actions directly usable by the Refiner Agent.
- Preserve the prompt semantics and safe SVG constraints.
- Do not generate SVG code.
- Do not include markdown.

Icon plan JSON:
{json.dumps(plan.to_json(), indent=2)}
{selector_context}
Failure taxonomy JSON:
{json.dumps(taxonomy.to_json(), indent=2)}

LLM validator report JSON:
{json.dumps(validation_report.to_json(), indent=2)}

Deterministic SvgCheckTool report JSON:
{json.dumps(tool_report.to_json(), indent=2)}

Round index: {round_index}

Current SVG:
{artifact.svg}
"""


def _refinement_prompt(
    plan: IconPlan,
    artifact: SvgArtifact,
    validation_report: ValidationReport,
    tool_report: ValidationReport,
    round_index: int,
    collaboration_brief: str | None = None,
    repair_route: RepairRoute | None = None,
) -> str:
    selector_context = (
        f"\nCollaborative selector repair brief:\n{collaboration_brief}\n"
        if collaboration_brief
        else ""
    )
    route_context = (
        f"\nRepair router JSON:\n{json.dumps(repair_route.to_json(), indent=2)}\n"
        if repair_route is not None
        else "\nRepair router JSON: none.\n"
    )
    return f"""Repair the SVG below and return only one complete SVG document.
Hard requirements:
- Canvas must be exactly <svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">.
- Include <title> and <desc>.
- Use only these SVG elements: svg, title, desc, path, circle, rect, line, polyline, polygon, ellipse.
- Use only literal #RRGGBB colors plus white, black, none, or transparent.
- Do not use style attributes, classes, defs, filters, gradients, transforms, text, script, image, foreignObject, animation, or external references.
- Keep 4 to 20 drawing primitives and preserve the prompt semantics.

Prompt: {plan.prompt}
Motifs: {", ".join(plan.motifs)}
Layout: {plan.layout}
Refinement round: {round_index}
{selector_context}
{route_context}

LLM validator report JSON:
{json.dumps(validation_report.to_json(), indent=2)}

Deterministic SVG check report JSON:
{json.dumps(tool_report.to_json(), indent=2)}

Current SVG:
{artifact.svg}
"""


def _json_object(content: str, label: str) -> dict[str, Any]:
    cleaned = _strip_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as first_exc:
        data = _first_json_object(cleaned)
        if data is None:
            message = (
                f"{label} response did not contain a JSON object."
                if "{" not in cleaned
                else f"{label} response JSON was malformed."
            )
            raise OpenRouterError(
                message,
                debug_payload={
                    "content_excerpt": cleaned[:4000],
                    "json_error": str(first_exc),
                },
            ) from first_exc
    if not isinstance(data, dict):
        raise OpenRouterError(
            f"{label} response JSON must be an object.",
            debug_payload={"content_excerpt": cleaned[:4000]},
        )
    return data


def _first_json_object(cleaned: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _coerce_plan(item: PromptItem, data: dict[str, Any]) -> IconPlan:
    category = data.get("category") if data.get("category") in VALID_CATEGORIES else item.category
    style = data.get("style") if data.get("style") in VALID_STYLES else item.style
    palette = _coerce_palette(data.get("palette"), item.palette)
    motifs = _coerce_string_tuple(data.get("motifs"), fallback=(item.category,))
    constraints = _coerce_string_tuple(data.get("constraints"), fallback=())
    constraints = _merge_constraints(
        constraints,
        (
            "safe-svg-primitives-only",
            "square-256-canvas",
            "no-external-assets",
            "high-contrast-silhouette",
        ),
    )
    layout = data.get("layout") if isinstance(data.get("layout"), str) and data.get("layout").strip() else "llm-layout"
    return IconPlan(
        id=item.id,
        category=str(category),
        prompt=item.prompt,
        style=str(style),
        palette=palette,
        motifs=motifs,
        layout=str(layout).strip().lower().replace(" ", "-"),
        constraints=constraints,
    )


def _coerce_goal(item: PromptItem, data: dict[str, Any], *, manual_goal: str | None) -> GenerationGoal:
    objective_fallback = manual_goal or f"Create a clear editable SVG icon for: {item.prompt}"
    return GenerationGoal(
        objective=_coerce_text(data.get("objective"), fallback=objective_fallback),
        visual_requirements=_coerce_string_tuple(
            data.get("visual_requirements"),
            fallback=("clear-main-silhouette", "small-size-readable"),
        ),
        constraints=_coerce_string_tuple(
            data.get("constraints"),
            fallback=("safe-svg-primitives-only", "square-256-canvas"),
        ),
        acceptance_criteria=_coerce_string_tuple(
            data.get("acceptance_criteria"),
            fallback=("recognizable-at-32px", "valid-safe-svg"),
        ),
        style_preferences=_coerce_string_tuple(data.get("style_preferences"), fallback=(item.style,)),
        avoid_patterns=_coerce_string_tuple(
            data.get("avoid_patterns"),
            fallback=("no-raster-images", "no-unnecessary-complexity"),
        ),
    )


def _coerce_memory_record(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _coerce_text(data.get("summary"), fallback="Reusable SVG icon generation lesson."),
        "success_patterns": list(_coerce_string_tuple(data.get("success_patterns"), fallback=())),
        "failure_patterns": list(_coerce_string_tuple(data.get("failure_patterns"), fallback=())),
        "user_feedback": list(_coerce_string_tuple(data.get("user_feedback"), fallback=())),
        "score": _coerce_score(data.get("score"), fallback=0),
        "tags": list(_coerce_string_tuple(data.get("tags"), fallback=())),
    }


def _coerce_validation_report(
    artifact: SvgArtifact,
    data: dict[str, Any],
    tool_report: ValidationReport,
) -> ValidationReport:
    score = _coerce_score(data.get("score"), fallback=tool_report.score)
    issues = _coerce_validation_issues(data.get("issues"))
    if data.get("valid") is False and not issues:
        issues.append(
            ValidationIssue(
                code="llm-invalid",
                severity="warning",
                message="LLM validator marked the SVG as invalid but did not list a specific issue.",
            )
        )

    seen_codes = {issue.code for issue in issues}
    for tool_issue in tool_report.issues:
        code = f"tool-{tool_issue.code}"
        if code in seen_codes or tool_issue.code in seen_codes:
            continue
        issues.append(
            ValidationIssue(
                code=code,
                severity=tool_issue.severity,
                message=f"Local SVG check: {tool_issue.message}",
            )
        )
        seen_codes.add(code)

    if not tool_report.is_valid:
        score = min(score, tool_report.score)

    return ValidationReport(
        id=artifact.id,
        stage=artifact.stage,
        score=score,
        issues=tuple(issues),
    )


def _coerce_failure_taxonomy(
    artifact: SvgArtifact,
    data: dict[str, Any],
    round_index: int,
) -> FailureTaxonomy:
    allowed_types = {
        "syntax_safety",
        "renderability",
        "semantic_mismatch",
        "visual_clarity",
        "editability",
        "constraint_violation",
    }
    failure_types = tuple(
        item for item in _coerce_string_tuple(data.get("failure_types"), fallback=("constraint_violation",))
        if item in allowed_types
    )
    priority = _coerce_text(data.get("priority"), fallback="medium").strip().lower()
    if priority not in {"low", "medium", "high", "critical"}:
        priority = "medium"
    return FailureTaxonomy(
        id=artifact.id,
        stage=artifact.stage,
        round_index=round_index,
        failure_types=failure_types or ("constraint_violation",),
        root_causes=_coerce_string_tuple(data.get("root_causes"), fallback=("validator-reported-blocking-issue",)),
        evidence=_coerce_string_tuple(data.get("evidence"), fallback=("validation-report-and-svg-check",)),
        priority=priority,
        repair_goals=_coerce_string_tuple(data.get("repair_goals"), fallback=("produce-valid-safe-svg",)),
    )


def _coerce_repair_route(
    artifact: SvgArtifact,
    data: dict[str, Any],
    round_index: int,
) -> RepairRoute:
    allowed_routes = {
        "safety_rebuild",
        "semantic_recompose",
        "simplify_icon",
        "layout_rebalance",
        "minor_patch",
    }
    route = _coerce_text(data.get("route"), fallback="minor_patch").strip().lower()
    if route not in allowed_routes:
        route = "minor_patch"
    return RepairRoute(
        id=artifact.id,
        stage=artifact.stage,
        round_index=round_index,
        route=route,
        strategy=_coerce_text(data.get("strategy"), fallback="Repair blocking SVG validation issues while preserving the icon intent."),
        ordered_actions=_coerce_string_tuple(
            data.get("ordered_actions"),
            fallback=("fix-blocking-validation-issues", "preserve-safe-editable-svg-constraints"),
        ),
        refiner_brief=_coerce_text(data.get("refiner_brief"), fallback="Return a complete repaired SVG that addresses the validator and tool issues."),
        risk_notes=_coerce_string_tuple(data.get("risk_notes"), fallback=()),
    )


def _coerce_rewritten_prompt(item: PromptItem, data: dict[str, Any]) -> str:
    value = data.get("rewritten_prompt")
    if not isinstance(value, str) or not value.strip():
        raise OpenRouterError(
            "Prompt rewriter response did not include rewritten_prompt.",
            debug_payload={"content_excerpt": json.dumps(data)[:4000]},
        )
    rewritten = " ".join(value.strip().split())
    if len(rewritten) < 8:
        raise OpenRouterError(
            "Prompt rewriter returned a prompt that was too short.",
            debug_payload={"rewritten_prompt": rewritten, "original_prompt": item.prompt},
        )
    return rewritten[:500]


def _coerce_critiques(data: dict[str, Any], candidates: list[SvgArtifact]) -> tuple[CandidateCritique, ...]:
    candidate_ids = {candidate.stage for candidate in candidates}
    raw_critiques = data.get("critiques")
    if not isinstance(raw_critiques, list):
        raw_critiques = []

    by_id: dict[str, CandidateCritique] = {}
    for index, item in enumerate(raw_critiques):
        if not isinstance(item, dict):
            continue
        candidate_id = item.get("candidate_id")
        if candidate_id not in candidate_ids:
            continue
        by_id[str(candidate_id)] = CandidateCritique(
            candidate_id=str(candidate_id),
            score=_coerce_score(item.get("score"), fallback=0),
            strengths=_coerce_string_tuple(item.get("strengths"), fallback=()),
            issues=_coerce_string_tuple(item.get("issues"), fallback=()),
            recommendation=_coerce_text(item.get("recommendation"), fallback="No recommendation provided."),
        )

    critiques = []
    for candidate in candidates:
        critique = by_id.get(candidate.stage)
        if critique is None:
            critique = CandidateCritique(
                candidate_id=candidate.stage,
                score=0,
                strengths=(),
                issues=("missing-critic-report",),
                recommendation="Critic did not evaluate this candidate.",
            )
        critiques.append(critique)
    return tuple(critiques)


def _coerce_selection(
    data: dict[str, Any],
    candidates: list[SvgArtifact],
    response: OpenRouterResponse,
) -> LlmSelectionResult:
    candidate_ids = [candidate.stage for candidate in candidates]
    winner = data.get("winner_candidate_id")
    if winner not in candidate_ids:
        raise OpenRouterError(
            "Consensus selector did not choose a listed candidate.",
            debug_payload={
                "winner_candidate_id": winner,
                "candidate_ids": candidate_ids,
                "content_excerpt": response.content[:4000],
            },
        )
    return LlmSelectionResult(
        winner_candidate_id=str(winner),
        rationale=_coerce_text(data.get("rationale"), fallback="Selector chose the strongest available candidate."),
        risks=_coerce_string_tuple(data.get("risks"), fallback=()),
        repair_brief=_coerce_text(data.get("repair_brief"), fallback="Refine the selected candidate while preserving its meaning."),
        response=response,
    )


def _coerce_score(value: Any, fallback: int) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = fallback
    return max(0, min(100, score))


def _coerce_validation_issues(value: Any) -> list[ValidationIssue]:
    if not isinstance(value, list):
        return []
    issues: list[ValidationIssue] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        severity = item.get("severity")
        message = item.get("message")
        if not isinstance(code, str) or not code.strip():
            code = f"llm-issue-{index + 1}"
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        if not isinstance(message, str) or not message.strip():
            message = "LLM validator reported an issue without details."
        issues.append(
            ValidationIssue(
                code=code.strip().lower().replace(" ", "-"),
                severity=severity,
                message=message.strip(),
            )
        )
    return issues


def _coerce_palette(value: Any, fallback: tuple[str, str, str]) -> tuple[str, str, str]:
    if not isinstance(value, list) or len(value) != 3:
        return fallback
    colors = tuple(str(color).strip() for color in value)
    if not all(HEX_RE.match(color) for color in colors):
        return fallback
    return (colors[0], colors[1], colors[2])


def _coerce_text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _coerce_string_tuple(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return fallback
    cleaned = []
    for item in value:
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip().lower().replace(" ", "-"))
    return tuple(cleaned) if cleaned else fallback


def _merge_constraints(existing: tuple[str, ...], required: tuple[str, ...]) -> tuple[str, ...]:
    merged = list(existing)
    for item in required:
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def _goal_json_text(goal: GenerationGoal | None) -> str:
    if goal is None:
        return "No generation goal provided."
    return json.dumps(goal.to_json(), indent=2)


def _memory_context_text(memory_context: MemoryContext | None) -> str:
    if memory_context is None or not memory_context.records:
        return "No retrieved memories."
    rows = []
    for item in memory_context.records:
        record = item.record
        rows.append(
            {
                "id": record.id,
                "score": round(item.score, 4),
                "prompt": record.prompt,
                "summary": record.summary,
                "success_patterns": list(record.success_patterns[:3]),
                "failure_patterns": list(record.failure_patterns[:3]),
                "user_feedback": list(record.user_feedback[:3]),
                "tags": list(record.tags[:6]),
            }
        )
    return json.dumps(rows, indent=2)


def _trim_trace(trace: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "workflow",
        "selected_candidate_id",
        "selector_rationale",
        "selector_repair_brief",
        "manual_optimizer_feedback",
        "post_run_optimizer_feedback",
        "baseline_score",
        "baseline_valid",
        "refined_score",
        "refined_valid",
        "score_delta",
        "errors",
    }
    return {key: value for key, value in trace.items() if key in allowed}


def _extract_svg(content: str) -> str:
    cleaned = _strip_fence(content)
    match = re.search(r"<svg\b.*?</svg>", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise OpenRouterError("SVG generator response did not contain a complete <svg> document.")
    return match.group(0).strip() + "\n"


def _strip_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()
