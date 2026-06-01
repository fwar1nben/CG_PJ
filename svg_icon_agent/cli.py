"""CLI wiring for the SVG Icon Agent pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from svg_icon_agent.backends import generate_with_backend
from svg_icon_agent.exporter import export_artifacts
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL
from svg_icon_agent.prompts import load_prompts
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.validator import validate_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate SVG icons from English prompts.")
    parser.add_argument("--prompt", required=True, help="Path to a JSON prompt list.")
    parser.add_argument("--out", default="outputs", help="Output directory.")
    parser.add_argument("--max-refine-rounds", type=int, default=3, help="Maximum repair rounds.")
    parser.add_argument(
        "--backend",
        choices=["rule", "openrouter", "auto"],
        default="auto",
        help="Generation backend. auto uses OpenRouter when OPENROUTER_API_KEY is set.",
    )
    parser.add_argument("--model", default=DEFAULT_OPENROUTER_MODEL, help="OpenRouter model id.")
    parser.add_argument(
        "--llm-stage",
        choices=["plan", "plan-svg"],
        default="plan-svg",
        help="Use the LLM for planning only or for both planning and SVG drafting.",
    )
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
    backend_result = generate_with_backend(
        prompts,
        backend=args.backend,
        model=args.model,
        llm_stage=args.llm_stage,
    )
    plans = backend_result.plans
    artifacts = backend_result.artifacts

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
    report_by_id = {report.id: report for report in reports}
    refined_report_by_id = {report.id: report for report in refined_reports}
    (output_dir / "llm_trace.json").write_text(
        json.dumps(
            [
                trace.to_json(
                    baseline_report=report_by_id.get(trace.id),
                    refined_report=refined_report_by_id.get(trace.id),
                )
                for trace in backend_result.traces
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = export_artifacts(
        output_dir=output_dir,
        prompts=prompts,
        baseline_artifacts=artifacts,
        refined_artifacts=refined_artifacts,
        baseline_reports=reports,
        refined_reports=refined_reports,
        refinements=refinements,
    )
    valid_count = sum(report.is_valid for report in reports)
    refined_valid_count = sum(report.is_valid for report in refined_reports)
    print(
        f"Generated {len(artifacts)} baseline SVG icons in {baseline_dir}. "
        f"Backend={backend_result.active_backend}. "
        f"Validator accepted {valid_count}/{len(reports)} baseline and "
        f"{refined_valid_count}/{len(refined_reports)} refined icons. "
        f"Average score improved by {summary['average_score_delta']}."
    )
    return 0
