"""OpenRouter-backed planner and SVG draft agents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from svg_icon_agent.models import IconPlan, SvgArtifact
from svg_icon_agent.openrouter_client import OpenRouterClient, OpenRouterError, OpenRouterResponse
from svg_icon_agent.prompts import HEX_RE, PromptItem, VALID_CATEGORIES, VALID_STYLES


@dataclass(frozen=True)
class LlmPlanResult:
    plan: IconPlan
    response: OpenRouterResponse


@dataclass(frozen=True)
class LlmSvgResult:
    artifact: SvgArtifact
    response: OpenRouterResponse


class OpenRouterPlannerAgent:
    """Uses an OpenRouter model to produce an IconPlan-compatible JSON object."""

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

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
            temperature=0.2,
            max_tokens=900,
        )
        data = _json_object(response.content)
        return LlmPlanResult(plan=_coerce_plan(item, data), response=response)


class OpenRouterSvgGeneratorAgent:
    """Uses an OpenRouter model to draft a safe, compact SVG icon."""

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

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
            temperature=0.25,
            max_tokens=1800,
        )
        return LlmSvgResult(
            artifact=SvgArtifact(id=plan.id, stage=stage, svg=_extract_svg(response.content)),
            response=response,
        )


def _plan_prompt(item: PromptItem) -> str:
    palette = ", ".join(item.palette)
    return f"""Create a JSON object for a 256x256 SVG icon plan.
Required keys:
- category: one of ui, object, scene
- style: one of line, filled, mixed
- palette: exactly three #RRGGBB colors
- motifs: 2 to 6 short lowercase motif tokens
- layout: short layout name
- constraints: 4 to 8 short lowercase constraint tokens

Use this input as the source of truth:
id: {item.id}
category hint: {item.category}
style hint: {item.style}
palette hint: {palette}
prompt: {item.prompt}
"""


def _svg_prompt(plan: IconPlan) -> str:
    palette = ", ".join(plan.palette)
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
Palette: {palette}
Motifs: {motifs}
Layout: {plan.layout}
Constraints: {constraints}
"""


def _json_object(content: str) -> dict[str, Any]:
    cleaned = _strip_fence(content)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise OpenRouterError("Planner response did not contain a JSON object.")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise OpenRouterError("Planner response JSON must be an object.")
    return data


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

