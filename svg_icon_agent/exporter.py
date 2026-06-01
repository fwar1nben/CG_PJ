"""Artifact exporter for PNG previews, metrics, and HTML galleries."""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw

from svg_icon_agent.models import SvgArtifact, ValidationReport
from svg_icon_agent.prompts import PromptItem
from svg_icon_agent.refiner import RefinementResult

CANVAS = 256
PATH_TOKEN_RE = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def export_artifacts(
    output_dir: Path,
    prompts: list[PromptItem],
    baseline_artifacts: list[SvgArtifact],
    refined_artifacts: list[SvgArtifact],
    baseline_reports: list[ValidationReport],
    refined_reports: list[ValidationReport],
    refinements: list[RefinementResult],
) -> dict[str, object]:
    png_dir = output_dir / "png"
    baseline_png_dir = png_dir / "baseline"
    refined_png_dir = png_dir / "refined"
    baseline_png_dir.mkdir(parents=True, exist_ok=True)
    refined_png_dir.mkdir(parents=True, exist_ok=True)

    for artifact in baseline_artifacts:
        render_svg_to_png(artifact.svg, baseline_png_dir / f"{artifact.id}.png")
    for artifact in refined_artifacts:
        render_svg_to_png(artifact.svg, refined_png_dir / f"{artifact.id}.png")

    summary = _summary(baseline_reports, refined_reports, refinements)
    (output_dir / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "gallery.html").write_text(
        _gallery_html(prompts, baseline_reports, refined_reports, refinements),
        encoding="utf-8",
    )
    return summary


def render_svg_to_png(svg: str, path: Path) -> None:
    root = ET.fromstring(svg)
    image = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    for element in root.iter():
        tag = _local_name(element.tag)
        attrs = element.attrib
        fill = _color(attrs.get("fill"), attrs.get("opacity"))
        stroke = _color(attrs.get("stroke"), attrs.get("opacity"))
        stroke_width = int(float(attrs.get("stroke-width", "1")))

        if tag == "rect":
            x = _num(attrs.get("x"))
            y = _num(attrs.get("y"))
            w = _num(attrs.get("width"))
            h = _num(attrs.get("height"))
            radius = _num(attrs.get("rx"))
            if radius > 0:
                draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=stroke, width=stroke_width)
            else:
                draw.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=stroke_width)
        elif tag == "circle":
            cx = _num(attrs.get("cx"))
            cy = _num(attrs.get("cy"))
            r = _num(attrs.get("r"))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=stroke, width=stroke_width)
        elif tag == "ellipse":
            cx = _num(attrs.get("cx"))
            cy = _num(attrs.get("cy"))
            rx = _num(attrs.get("rx"))
            ry = _num(attrs.get("ry"))
            draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill, outline=stroke, width=stroke_width)
        elif tag == "line":
            draw.line(
                [_num(attrs.get("x1")), _num(attrs.get("y1")), _num(attrs.get("x2")), _num(attrs.get("y2"))],
                fill=stroke or fill,
                width=stroke_width,
            )
        elif tag in {"polyline", "polygon"}:
            points = _points(attrs.get("points", ""))
            if tag == "polygon":
                draw.polygon(points, fill=fill, outline=stroke)
                if stroke and stroke_width > 1:
                    draw.line(points + [points[0]], fill=stroke, width=stroke_width)
            else:
                draw.line(points, fill=stroke or fill, width=stroke_width)
        elif tag == "path":
            points, closed = _path_points(attrs.get("d", ""))
            if len(points) >= 2:
                if fill and closed:
                    draw.polygon(points, fill=fill)
                if stroke:
                    draw.line(points + ([points[0]] if closed else []), fill=stroke, width=stroke_width)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path)


def _summary(
    baseline_reports: list[ValidationReport],
    refined_reports: list[ValidationReport],
    refinements: list[RefinementResult],
) -> dict[str, object]:
    baseline_scores = [report.score for report in baseline_reports]
    refined_scores = [report.score for report in refined_reports]
    return {
        "total": len(refined_reports),
        "baseline_valid": sum(report.is_valid for report in baseline_reports),
        "refined_valid": sum(report.is_valid for report in refined_reports),
        "baseline_average_score": round(sum(baseline_scores) / len(baseline_scores), 2),
        "refined_average_score": round(sum(refined_scores) / len(refined_scores), 2),
        "average_score_delta": round(
            sum(result.to_json()["score_delta"] for result in refinements) / len(refinements),
            2,
        ),
        "max_rounds_used": max(result.rounds_used for result in refinements),
    }


def _gallery_html(
    prompts: list[PromptItem],
    baseline_reports: list[ValidationReport],
    refined_reports: list[ValidationReport],
    refinements: list[RefinementResult],
) -> str:
    baseline_by_id = {report.id: report for report in baseline_reports}
    refined_by_id = {report.id: report for report in refined_reports}
    refinement_by_id = {result.id: result for result in refinements}
    cards = []
    for item in prompts:
        baseline = baseline_by_id[item.id]
        refined = refined_by_id[item.id]
        refinement = refinement_by_id[item.id]
        cards.append(
            f"""
      <article class="card">
        <header>
          <h2>{html.escape(item.id)}</h2>
          <p>{html.escape(item.prompt)}</p>
        </header>
        <div class="pair">
          <figure>
            <img src="png/baseline/{item.id}.png" alt="Baseline {html.escape(item.id)}">
            <figcaption>Baseline score {baseline.score}</figcaption>
          </figure>
          <figure>
            <img src="png/refined/{item.id}.png" alt="Refined {html.escape(item.id)}">
            <figcaption>Refined score {refined.score}, {refinement.rounds_used} round</figcaption>
          </figure>
        </div>
      </article>"""
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SVG Icon Agent Gallery</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #111827;
      background: #f8fafc;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
    }}
    .summary {{
      margin: 0 0 24px;
      color: #475569;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
    }}
    .card {{
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 16px;
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
    }}
    p {{
      margin: 8px 0 14px;
      color: #475569;
      line-height: 1.45;
    }}
    .pair {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}
    figure {{
      margin: 0;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 10px;
      background: #f8fafc;
    }}
    img {{
      display: block;
      width: 100%;
      aspect-ratio: 1;
      object-fit: contain;
      background: white;
      border-radius: 6px;
    }}
    figcaption {{
      margin-top: 8px;
      color: #334155;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>SVG Icon Agent Gallery</h1>
    <p class="summary">Baseline and refined outputs from the deterministic multi-agent SVG pipeline.</p>
    <section class="grid">
{''.join(cards)}
    </section>
  </main>
</body>
</html>
"""


def _path_points(d: str) -> tuple[list[tuple[float, float]], bool]:
    tokens = PATH_TOKEN_RE.findall(d)
    points: list[tuple[float, float]] = []
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    command = ""
    previous_quad_control: tuple[float, float] | None = None
    i = 0
    closed = False
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command.upper() == "Z":
                closed = True
                current = start
                points.append(start)
            continue

        op = command.upper()
        relative = command.islower()
        if op == "M" and _has_numbers(tokens, i, 2):
            current = _resolve_point(current, float(tokens[i]), float(tokens[i + 1]), relative)
            start = current
            points.append(current)
            i += 2
            command = "l" if relative else "L"
            previous_quad_control = None
        elif op == "L" and _has_numbers(tokens, i, 2):
            current = _resolve_point(current, float(tokens[i]), float(tokens[i + 1]), relative)
            points.append(current)
            i += 2
            previous_quad_control = None
        elif op == "H" and _has_numbers(tokens, i, 1):
            x = current[0] + float(tokens[i]) if relative else float(tokens[i])
            current = (x, current[1])
            points.append(current)
            i += 1
            previous_quad_control = None
        elif op == "V" and _has_numbers(tokens, i, 1):
            y = current[1] + float(tokens[i]) if relative else float(tokens[i])
            current = (current[0], y)
            points.append(current)
            i += 1
            previous_quad_control = None
        elif op == "C" and _has_numbers(tokens, i, 6):
            p0 = current
            p1 = _resolve_point(current, float(tokens[i]), float(tokens[i + 1]), relative)
            p2 = _resolve_point(current, float(tokens[i + 2]), float(tokens[i + 3]), relative)
            p3 = _resolve_point(current, float(tokens[i + 4]), float(tokens[i + 5]), relative)
            for step in range(1, 15):
                t = step / 14
                points.append(_cubic(p0, p1, p2, p3, t))
            current = p3
            i += 6
            previous_quad_control = None
        elif op == "S" and _has_numbers(tokens, i, 4):
            current = _resolve_point(current, float(tokens[i + 2]), float(tokens[i + 3]), relative)
            points.append(current)
            i += 4
            previous_quad_control = None
        elif op == "Q" and _has_numbers(tokens, i, 4):
            p0 = current
            p1 = _resolve_point(current, float(tokens[i]), float(tokens[i + 1]), relative)
            p2 = _resolve_point(current, float(tokens[i + 2]), float(tokens[i + 3]), relative)
            for step in range(1, 13):
                t = step / 12
                points.append(_quadratic(p0, p1, p2, t))
            current = p2
            previous_quad_control = p1
            i += 4
        elif op == "T" and _has_numbers(tokens, i, 2):
            p0 = current
            reflected = (
                (2 * current[0] - previous_quad_control[0], 2 * current[1] - previous_quad_control[1])
                if previous_quad_control is not None
                else current
            )
            p2 = _resolve_point(current, float(tokens[i]), float(tokens[i + 1]), relative)
            for step in range(1, 13):
                t = step / 12
                points.append(_quadratic(p0, reflected, p2, t))
            current = p2
            previous_quad_control = reflected
            i += 2
        elif op == "A" and _has_numbers(tokens, i, 7):
            current = _resolve_point(current, float(tokens[i + 5]), float(tokens[i + 6]), relative)
            points.append(current)
            i += 7
            previous_quad_control = None
        elif token.isalpha():
            previous_quad_control = None
        else:
            i += 1
    return points, closed


def _has_numbers(tokens: list[str], index: int, count: int) -> bool:
    return index + count <= len(tokens) and all(not tokens[index + offset].isalpha() for offset in range(count))


def _resolve_point(
    current: tuple[float, float],
    x: float,
    y: float,
    relative: bool,
) -> tuple[float, float]:
    if relative:
        return (current[0] + x, current[1] + y)
    return (x, y)


def _cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    mt = 1 - t
    x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
    y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
    return x, y


def _quadratic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    mt = 1 - t
    x = mt**2 * p0[0] + 2 * mt * t * p1[0] + t**2 * p2[0]
    y = mt**2 * p0[1] + 2 * mt * t * p1[1] + t**2 * p2[1]
    return x, y


def _points(raw: str) -> list[tuple[float, float]]:
    nums = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", raw)]
    return list(zip(nums[0::2], nums[1::2], strict=False))


def _num(value: str | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _color(value: str | None, opacity: str | None = None) -> tuple[int, int, int, int] | None:
    if value is None or value == "none":
        return None
    alpha = int(255 * float(opacity or "1"))
    if value == "white":
        return (255, 255, 255, alpha)
    if value == "black":
        return (0, 0, 0, alpha)
    if value.startswith("#") and len(value) == 7:
        return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), alpha)
    return (17, 24, 39, alpha)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
