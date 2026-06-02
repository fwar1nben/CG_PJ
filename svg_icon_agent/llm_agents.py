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
DEFAULT_SVG_MAX_TOKENS = 1800
DEFAULT_VALIDATOR_MAX_TOKENS = 1200
DEFAULT_REFINER_MAX_TOKENS = 2200


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
                    "content": _refinement_prompt(plan, artifact, validation_report, tool_report, round_index),
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
) -> str:
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
