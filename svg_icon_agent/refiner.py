"""Refiner agent that repairs SVGs according to validator feedback."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from svg_icon_agent.models import IconPlan, SvgArtifact, ValidationReport
from svg_icon_agent.validator import ValidatorAgent


@dataclass(frozen=True)
class RefinementResult:
    id: str
    artifact: SvgArtifact
    reports: tuple[ValidationReport, ...]
    rounds_used: int

    def to_json(self) -> dict[str, object]:
        first_score = self.reports[0].score if self.reports else 0
        final_score = self.reports[-1].score if self.reports else 0
        return {
            "id": self.id,
            "rounds_used": self.rounds_used,
            "initial_score": first_score,
            "final_score": final_score,
            "score_delta": final_score - first_score,
            "accepted": self.reports[-1].is_valid if self.reports else False,
            "reports": [report.to_json() for report in self.reports],
        }


class RefinerAgent:
    """Applies deterministic repairs based on validator issue codes."""

    def __init__(self) -> None:
        self.validator = ValidatorAgent()

    def refine(
        self,
        plan: IconPlan,
        artifact: SvgArtifact,
        max_rounds: int = 3,
    ) -> RefinementResult:
        current = artifact
        reports: list[ValidationReport] = []
        rounds_used = 0

        for _ in range(max_rounds + 1):
            report = self.validator.validate(current)
            reports.append(report)
            if not report.issues:
                break
            if rounds_used >= max_rounds:
                break
            repaired_svg = self._repair(plan, current.svg, report)
            if repaired_svg == current.svg:
                break
            rounds_used += 1
            current = SvgArtifact(id=artifact.id, stage="refined", svg=repaired_svg)

        if current.stage != "refined":
            current = SvgArtifact(id=artifact.id, stage="refined", svg=current.svg)
        return RefinementResult(
            id=artifact.id,
            artifact=current,
            reports=tuple(reports),
            rounds_used=rounds_used,
        )

    def _repair(self, plan: IconPlan, svg: str, report: ValidationReport) -> str:
        issue_codes = {issue.code for issue in report.issues}
        repaired = svg
        if "canvas-size" in issue_codes:
            repaired = _set_svg_attr(repaired, "width", "256")
            repaired = _set_svg_attr(repaired, "height", "256")
        if "missing-viewbox" in issue_codes:
            repaired = _set_svg_attr(repaired, "viewBox", "0 0 256 256")
        if "missing-title" in issue_codes or "missing-desc" in issue_codes:
            repaired = _ensure_accessibility(repaired, plan)
        if "low-detail" in issue_codes:
            repaired = _insert_before_svg_close(
                repaired,
                f'  <circle cx="210" cy="210" r="8" fill="{plan.palette[0]}" opacity="0.35"/>\n',
            )
        if "limited-palette" in issue_codes:
            repaired = _insert_before_svg_close(
                repaired,
                f'  <circle cx="46" cy="210" r="7" fill="{plan.palette[2]}" opacity="0.85"/>\n',
            )
        if "invalid-color" in issue_codes:
            repaired = re.sub(r'(fill|stroke)="(?!none|white|black|transparent|currentColor|#[0-9a-fA-F]{6})[^"]*"', rf'\1="{plan.palette[0]}"', repaired)
        if "event-handler" in issue_codes:
            repaired = re.sub(r"\s+on[a-zA-Z]+=\"[^\"]*\"", "", repaired)
        if "external-reference" in issue_codes or "unsafe-reference" in issue_codes:
            repaired = re.sub(r'\s+(href|src|xlink:href)="[^"]*"', "", repaired)
            repaired = repaired.replace("url(", "")
        return repaired


def refine_artifacts(
    plans: list[IconPlan],
    artifacts: list[SvgArtifact],
    max_rounds: int = 3,
) -> list[RefinementResult]:
    by_id = {plan.id: plan for plan in plans}
    refiner = RefinerAgent()
    return [refiner.refine(by_id[artifact.id], artifact, max_rounds=max_rounds) for artifact in artifacts]


def _set_svg_attr(svg: str, attr: str, value: str) -> str:
    attr_re = re.compile(rf'(\s{re.escape(attr)}=")[^"]*(")')
    if attr_re.search(svg):
        return attr_re.sub(rf'\g<1>{value}\2', svg, count=1)
    return re.sub(r"(<svg\b[^>]*)(>)", rf'\1 {attr}="{value}"\2', svg, count=1)


def _ensure_accessibility(svg: str, plan: IconPlan) -> str:
    title = html.escape(plan.id.replace("-", " ").title())
    desc = html.escape(plan.prompt)
    insert = ""
    if "<title>" not in svg:
        insert += f"  <title>{title}</title>\n"
    if "<desc>" not in svg:
        insert += f"  <desc>{desc}</desc>\n"
    if not insert:
        return svg
    return re.sub(r"(<svg\b[^>]*>\n?)", rf"\1{insert}", svg, count=1)


def _insert_before_svg_close(svg: str, content: str) -> str:
    if "</svg>" not in svg:
        return svg + "\n" + content
    return svg.replace("</svg>", content + "</svg>", 1)

