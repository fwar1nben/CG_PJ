"""OpenRouter-backed agents for the SVG icon pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from svg_icon_agent.models import IconPlan, SvgArtifact, ValidationIssue, ValidationReport
from svg_icon_agent.openrouter_client import OpenRouterClient, OpenRouterError, OpenRouterResponse
from svg_icon_agent.prompts import HEX_RE, PromptItem, VALID_CATEGORIES, VALID_STYLES

DEFAULT_PLANNER_MAX_TOKENS = 900
DEFAULT_REWRITER_MAX_TOKENS = 700
DEFAULT_SVG_MAX_TOKENS = 1800
DEFAULT_VALIDATOR_MAX_TOKENS = 1200
DEFAULT_REFINER_MAX_TOKENS = 2200


@dataclass(frozen=True)
class LlmRewriteResult:
    item: PromptItem
    rewritten_prompt: str
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
class LlmRefinementResult:
    artifact: SvgArtifact
    response: OpenRouterResponse


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


class OpenRouterPromptRewriterAgent:
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

    def rewrite(self, item: PromptItem) -> LlmRewriteResult:
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
                    "content": _rewrite_prompt(item),
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


class OpenRouterPlannerAgent:
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

    def plan(self, item: PromptItem) -> LlmPlanResult:
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
                    "content": _plan_prompt(item),
                },
            ],
            response_format={"type": "json_object"},
            reasoning=self.reasoning,
            temperature=0.2,
            max_tokens=self.max_tokens or DEFAULT_PLANNER_MAX_TOKENS,
        )
        data = _json_object(response.content, "Planner")
        return LlmPlanResult(plan=_coerce_plan(item, data), response=response)


class OpenRouterSvgGeneratorAgent:
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

    def generate(self, plan: IconPlan, stage: str = "baseline") -> LlmSvgResult:
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
                    "content": _svg_prompt(plan),
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


class OpenRouterMultiCandidateGeneratorAgent:
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

    def generate_one(self, plan: IconPlan, *, candidate_index: int, candidate_count: int) -> LlmSvgResult:
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
                    "content": _candidate_svg_prompt(plan, candidate_index, candidate_count),
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


class OpenRouterValidatorAgent:
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


class OpenRouterSemanticCriticAgent:
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


class OpenRouterSvgQualityCriticAgent:
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


class OpenRouterConsensusSelectorAgent:
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


class OpenRouterRefinerAgent:
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


def _rewrite_prompt(item: PromptItem) -> str:
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
"""


def _plan_prompt(item: PromptItem) -> str:
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
"""


def _svg_prompt(plan: IconPlan) -> str:
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
"""


def _candidate_svg_prompt(plan: IconPlan, candidate_index: int, candidate_count: int) -> str:
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


def _refinement_prompt(
    plan: IconPlan,
    artifact: SvgArtifact,
    validation_report: ValidationReport,
    tool_report: ValidationReport,
    round_index: int,
    collaboration_brief: str | None = None,
) -> str:
    selector_context = (
        f"\nCollaborative selector repair brief:\n{collaboration_brief}\n"
        if collaboration_brief
        else ""
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
