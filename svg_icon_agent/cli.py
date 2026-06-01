"""CLI wiring for the SVG Icon Agent pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from svg_icon_agent.backends import generate_with_backend
from svg_icon_agent.exporter import export_artifacts
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL
from svg_icon_agent.progress import ProgressLogger
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
        "--request-timeout",
        type=float,
        default=60.0,
        help="Per-request OpenRouter timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry count for retryable OpenRouter request failures.",
    )
    parser.add_argument(
        "--llm-stage",
        choices=["plan", "plan-svg"],
        default="plan-svg",
        help="Use the LLM for planning only or for both planning and SVG drafting.",
    )
    parser.add_argument("--quiet", action="store_true", help="Hide progress logs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.out)
    baseline_dir = output_dir / "baseline"
    refined_dir = output_dir / "refined"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)

    progress = ProgressLogger(verbose=not args.quiet)
    progress.log(f"Loading prompts from {args.prompt}.")
    prompts = load_prompts(args.prompt)
    progress.log(f"Loaded {len(prompts)} prompts.")
    backend_result = generate_with_backend(
        prompts,
        backend=args.backend,
        model=args.model,
        llm_stage=args.llm_stage,
        request_timeout=args.request_timeout,
        max_retries=args.max_retries,
        progress=progress,
    )
    plans = backend_result.plans
    artifacts = backend_result.artifacts

    progress.log(f"Writing {len(artifacts)} baseline SVG files.")
    for artifact in artifacts:
        (baseline_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")
    progress.log("Validating baseline SVG files.")
    reports = validate_artifacts(artifacts)
    progress.log("Running deterministic refinement loop.")
    refinements = refine_artifacts(plans, artifacts, max_rounds=args.max_refine_rounds)
    refined_artifacts = [result.artifact for result in refinements]
    progress.log("Validating refined SVG files.")
    refined_reports = validate_artifacts(refined_artifacts)

    progress.log(f"Writing {len(refined_artifacts)} refined SVG files.")
    for artifact in refined_artifacts:
        (refined_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")

    progress.log("Writing JSON reports and LLM trace.")
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
    (output_dir / "llm_raw_responses.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in backend_result.raw_llm_events),
        encoding="utf-8",
    )
    progress.log("Exporting PNG previews and gallery.")
    summary = export_artifacts(
        output_dir=output_dir,
        prompts=prompts,
        baseline_artifacts=artifacts,
        refined_artifacts=refined_artifacts,
        baseline_reports=reports,
        refined_reports=refined_reports,
        refinements=refinements,
    )
    progress.log("Pipeline complete.")
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
