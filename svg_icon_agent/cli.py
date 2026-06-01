"""CLI wiring for the SVG Icon Agent pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from svg_icon_agent.generator import SvgGeneratorAgent
from svg_icon_agent.planner import plan_prompts
from svg_icon_agent.prompts import load_prompts
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.validator import validate_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate SVG icons from English prompts.")
    parser.add_argument("--prompt", required=True, help="Path to a JSON prompt list.")
    parser.add_argument("--out", default="outputs", help="Output directory.")
    parser.add_argument("--max-refine-rounds", type=int, default=3, help="Maximum repair rounds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.out)
    baseline_dir = output_dir / "baseline"
    refined_dir = output_dir / "refined"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)

    prompts = load_prompts(args.prompt)
    plans = plan_prompts(prompts)
    generator = SvgGeneratorAgent()
    artifacts = [generator.generate(plan) for plan in plans]

    for artifact in artifacts:
        (baseline_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")
    reports = validate_artifacts(artifacts)
    refinements = refine_artifacts(plans, artifacts, max_rounds=args.max_refine_rounds)
    refined_artifacts = [result.artifact for result in refinements]
    refined_reports = validate_artifacts(refined_artifacts)

    for artifact in refined_artifacts:
        (refined_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")

    (output_dir / "plans.json").write_text(
        json.dumps([plan.to_json() for plan in plans], indent=2),
        encoding="utf-8",
    )
    (output_dir / "baseline_validation.json").write_text(
        json.dumps([report.to_json() for report in reports], indent=2),
        encoding="utf-8",
    )
    (output_dir / "refined_validation.json").write_text(
        json.dumps([report.to_json() for report in refined_reports], indent=2),
        encoding="utf-8",
    )
    (output_dir / "refinement_history.json").write_text(
        json.dumps([result.to_json() for result in refinements], indent=2),
        encoding="utf-8",
    )
    valid_count = sum(report.is_valid for report in reports)
    refined_valid_count = sum(report.is_valid for report in refined_reports)
    print(
        f"Generated {len(artifacts)} baseline SVG icons in {baseline_dir}. "
        f"Validator accepted {valid_count}/{len(reports)} baseline and "
        f"{refined_valid_count}/{len(refined_reports)} refined icons."
    )
    return 0
