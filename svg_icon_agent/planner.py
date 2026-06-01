"""Rule-based planner agent for prompt decomposition."""

from __future__ import annotations

from svg_icon_agent.models import IconPlan
from svg_icon_agent.prompts import PromptItem

MOTIF_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cloud", ("cloud",)),
    ("download", ("download", "downward arrow")),
    ("shield", ("shield", "security")),
    ("lock", ("lock",)),
    ("calendar", ("calendar",)),
    ("check", ("check", "check mark")),
    ("chat", ("chat", "bubble")),
    ("sparkle", ("sparkle",)),
    ("camera", ("camera", "lens")),
    ("coffee", ("coffee", "cup", "steam")),
    ("rocket", ("rocket", "flame")),
    ("book", ("book", "education")),
    ("pencil", ("pencil",)),
    ("mountain", ("mountain", "landscape")),
    ("sun", ("sun", "rising")),
    ("city", ("city", "skyline")),
    ("moon", ("moon", "night")),
    ("forest", ("forest", "tree")),
    ("path", ("path", "trail")),
    ("planet", ("planet", "science")),
    ("flask", ("flask", "lab")),
)

LAYOUT_BY_CATEGORY = {
    "ui": "centered-symbol",
    "object": "single-object",
    "scene": "layered-scene",
}


class PlannerAgent:
    """Extracts a compact icon plan from an English prompt."""

    def plan(self, item: PromptItem) -> IconPlan:
        lowered = item.prompt.lower()
        motifs = [
            motif
            for motif, keywords in MOTIF_KEYWORDS
            if any(keyword in lowered for keyword in keywords)
        ]
        if not motifs:
            motifs = [item.category]

        constraints = [
            "safe-svg-primitives-only",
            "square-256-canvas",
            "no-external-assets",
            "high-contrast-silhouette",
        ]
        if "no text" in lowered:
            constraints.append("no-text")
        if "small size" in lowered or "compact" in lowered:
            constraints.append("readable-at-small-size")

        return IconPlan(
            id=item.id,
            category=item.category,
            prompt=item.prompt,
            style=item.style,
            palette=item.palette,
            motifs=tuple(motifs),
            layout=LAYOUT_BY_CATEGORY[item.category],
            constraints=tuple(constraints),
        )


def plan_prompts(items: list[PromptItem]) -> list[IconPlan]:
    planner = PlannerAgent()
    return [planner.plan(item) for item in items]

