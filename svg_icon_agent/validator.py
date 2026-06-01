"""Validator agent for SVG structure, safety, and simple design rules."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from svg_icon_agent.models import SvgArtifact, ValidationIssue, ValidationReport

ALLOWED_TAGS = {
    "svg",
    "title",
    "desc",
    "g",
    "path",
    "circle",
    "rect",
    "line",
    "polyline",
    "polygon",
    "ellipse",
}
DISALLOWED_TAGS = {"script", "foreignObject", "image", "iframe", "audio", "video", "animate"}
DRAWING_TAGS = {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NUMERIC_RE = re.compile(r"^\d+(\.\d+)?$")
SAFE_NAMED_COLORS = {"none", "white", "black", "transparent", "currentColor"}


class ValidatorAgent:
    """Checks SVG files before they are accepted as refined artifacts."""

    def validate(self, artifact: SvgArtifact) -> ValidationReport:
        issues: list[ValidationIssue] = []
        try:
            root = ET.fromstring(artifact.svg)
        except ET.ParseError as exc:
            return ValidationReport(
                id=artifact.id,
                stage=artifact.stage,
                score=0,
                issues=(
                    ValidationIssue(
                        code="xml-parse-error",
                        severity="error",
                        message=f"SVG XML is not parseable: {exc}.",
                    ),
                ),
            )

        if _local_name(root.tag) != "svg":
            issues.append(_issue("root-not-svg", "error", "Root element must be <svg>."))

        width = root.attrib.get("width")
        height = root.attrib.get("height")
        view_box = root.attrib.get("viewBox")
        if width != "256" or height != "256":
            issues.append(_issue("canvas-size", "error", "SVG must use width=\"256\" height=\"256\"."))
        if view_box != "0 0 256 256":
            issues.append(_issue("missing-viewbox", "error", "SVG must include viewBox=\"0 0 256 256\"."))

        title_count = 0
        desc_count = 0
        drawing_count = 0
        colors: set[str] = set()

        for element in root.iter():
            tag = _local_name(element.tag)
            if tag in DISALLOWED_TAGS:
                issues.append(_issue("unsafe-tag", "error", f"Disallowed tag <{tag}> found."))
            if tag not in ALLOWED_TAGS:
                issues.append(_issue("unsupported-tag", "error", f"Unsupported tag <{tag}> found."))
            if tag == "title":
                title_count += 1
            if tag == "desc":
                desc_count += 1
            if tag in DRAWING_TAGS:
                drawing_count += 1
            for attr_name, attr_value in element.attrib.items():
                _validate_attribute(attr_name, attr_value, issues, colors)

        if title_count == 0:
            issues.append(_issue("missing-title", "warning", "Add a <title> for accessibility and report clarity."))
        if desc_count == 0:
            issues.append(_issue("missing-desc", "warning", "Add a <desc> describing the icon intent."))
        if drawing_count < 4:
            issues.append(_issue("low-detail", "warning", "Icon should use at least four drawing primitives."))
        if drawing_count > 28:
            issues.append(_issue("too-complex", "warning", "Icon is complex for a compact icon; reduce primitive count."))
        if len(colors) < 2:
            issues.append(_issue("limited-palette", "warning", "Icon should use at least two visible colors."))

        score = _score(issues)
        return ValidationReport(
            id=artifact.id,
            stage=artifact.stage,
            score=score,
            issues=tuple(issues),
        )


def validate_artifacts(artifacts: list[SvgArtifact]) -> list[ValidationReport]:
    validator = ValidatorAgent()
    return [validator.validate(artifact) for artifact in artifacts]


def _validate_attribute(
    attr_name: str,
    attr_value: str,
    issues: list[ValidationIssue],
    colors: set[str],
) -> None:
    local_attr = _local_name(attr_name)
    value = attr_value.strip()
    if local_attr.startswith("on"):
        issues.append(_issue("event-handler", "error", f"Event handler attribute {local_attr} is not allowed."))
    if local_attr in {"href", "src"}:
        issues.append(_issue("external-reference", "error", f"External reference attribute {local_attr} is not allowed."))
    if "url(" in value or "javascript:" in value.lower():
        issues.append(_issue("unsafe-reference", "error", f"Unsafe reference found in {local_attr}."))
    if local_attr in {"width", "height", "cx", "cy", "r", "x", "y", "rx", "ry", "x1", "x2", "y1", "y2"}:
        if not NUMERIC_RE.match(value):
            issues.append(_issue("non-numeric-geometry", "error", f"{local_attr} must be numeric."))
    if local_attr in {"fill", "stroke"} and value not in SAFE_NAMED_COLORS:
        if not COLOR_RE.match(value):
            issues.append(_issue("invalid-color", "error", f"{local_attr} must be a safe color token: {value}."))
        else:
            colors.add(value.lower())


def _score(issues: list[ValidationIssue]) -> int:
    score = 100
    for issue in issues:
        score -= 25 if issue.severity == "error" else 8
    return max(0, score)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _issue(code: str, severity: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, severity=severity, message=message)

