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

