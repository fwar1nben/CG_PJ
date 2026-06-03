"""Shared data models for the SVG Icon Agent pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class IconPlan:
    id: str
    category: str
    prompt: str
    style: str
    palette: tuple[str, str, str]
    motifs: tuple[str, ...]
    layout: str
    constraints: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["palette"] = list(self.palette)
        data["motifs"] = list(self.motifs)
        data["constraints"] = list(self.constraints)
        return data


@dataclass(frozen=True)
class GenerationGoal:
    objective: str
    visual_requirements: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    style_preferences: tuple[str, ...]
    avoid_patterns: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "visual_requirements": list(self.visual_requirements),
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "style_preferences": list(self.style_preferences),
            "avoid_patterns": list(self.avoid_patterns),
        }


@dataclass(frozen=True)
class SvgArtifact:
    id: str
    stage: str
    svg: str


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str

    def to_json(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    id: str
    stage: str
    score: int
    issues: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return all(issue.severity != "error" for issue in self.issues)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "score": self.score,
            "is_valid": self.is_valid,
            "issues": [issue.to_json() for issue in self.issues],
        }


@dataclass(frozen=True)
class FailureTaxonomy:
    id: str
    stage: str
    round_index: int
    failure_types: tuple[str, ...]
    root_causes: tuple[str, ...]
    evidence: tuple[str, ...]
    priority: str
    repair_goals: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "round": self.round_index,
            "failure_types": list(self.failure_types),
            "root_causes": list(self.root_causes),
            "evidence": list(self.evidence),
            "priority": self.priority,
            "repair_goals": list(self.repair_goals),
        }


@dataclass(frozen=True)
class RepairRoute:
    id: str
    stage: str
    round_index: int
    route: str
    strategy: str
    ordered_actions: tuple[str, ...]
    refiner_brief: str
    risk_notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "round": self.round_index,
            "route": self.route,
            "strategy": self.strategy,
            "ordered_actions": list(self.ordered_actions),
            "refiner_brief": self.refiner_brief,
            "risk_notes": list(self.risk_notes),
        }
