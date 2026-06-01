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
