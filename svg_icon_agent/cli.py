"""CLI wiring for the SVG Icon Agent pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from svg_icon_agent.backends import BackendTrace, create_openrouter_client, generate_with_backend
from svg_icon_agent.exporter import export_artifacts
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL, OpenRouterError
from svg_icon_agent.progress import ProgressLogger
from svg_icon_agent.prompts import PromptItem, load_prompts, make_prompt_from_text, split_case_ids
from svg_icon_agent.refiner import RefinementResult, refine_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate SVG icons from English prompts.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--prompt", help="Path to a JSON prompt list.")
    input_group.add_argument("--text", help="Manual single English icon prompt.")
    input_group.add_argument("--interactive", action="store_true", help="Read one prompt from stdin.")
    parser.add_argument("--case-id", help="Comma-separated prompt ids to select from --prompt.")
    parser.add_argument("--list-cases", action="store_true", help="List prompt ids from --prompt and exit.")
    parser.add_argument("--out", default="outputs", help="Output directory.")
    parser.add_argument("--max-refine-rounds", type=int, default=3, help="Maximum LLM repair rounds.")
    parser.add_argument(
        "--backend",
        choices=["openrouter"],
        default="openrouter",
        help="Generation backend. Local rule generation has been removed.",
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
        choices=["plan-svg"],
        default="plan-svg",
        help="LLM must perform both planning and SVG drafting.",
    )
    parser.add_argument("--quiet", action="store_true", help="Hide progress logs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        prompts = _load_input_prompts(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.list_cases:
        if not args.prompt:
            parser.error("--list-cases requires --prompt.")
        _print_prompt_cases(prompts)
        return 0

    output_dir = Path(args.out)
    baseline_dir = output_dir / "baseline"
    refined_dir = output_dir / "refined"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)

    progress = ProgressLogger(verbose=not args.quiet)
    progress.log(f"Loaded {len(prompts)} prompt(s).")

    try:
        client = create_openrouter_client(
            model=args.model,
            request_timeout=args.request_timeout,
            max_retries=args.max_retries,
        )
        backend_result = generate_with_backend(
            prompts,
            backend=args.backend,
            model=args.model,
            llm_stage=args.llm_stage,
            client=client,
            request_timeout=args.request_timeout,
            max_retries=args.max_retries,
            progress=progress,
        )
    except (OpenRouterError, ValueError) as exc:
        print(f"OpenRouter pipeline setup failed: {exc}")
        return 1

    plans = backend_result.plans
    artifacts = backend_result.artifacts
    trace_by_id = {trace.id: trace for trace in backend_result.traces}

    progress.log(f"Writing {len(artifacts)} baseline SVG files.")
    for artifact in artifacts:
        (baseline_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")

    if not artifacts:
        _write_trace_outputs(output_dir, backend_result.traces, backend_result.raw_llm_events)
        print("No SVG artifacts were generated. See llm_trace.json and llm_raw_responses.jsonl for details.")
        return 1

    progress.log("Running LLM validation/refinement loop.")
    refinements = refine_artifacts(
        plans,
        artifacts,
        client=client,
        max_rounds=args.max_refine_rounds,
        model=args.model,
        progress=progress,
    )
    _merge_refinement_traces(trace_by_id, refinements)

    refined_artifacts = [result.artifact for result in refinements]
    baseline_reports = [result.baseline_report for result in refinements]
    refined_reports = [result.refined_report for result in refinements]

    progress.log(f"Writing {len(refined_artifacts)} refined SVG files.")
    for artifact in refined_artifacts:
        (refined_dir / f"{artifact.id}.svg").write_text(artifact.svg, encoding="utf-8")

    raw_events = list(backend_result.raw_llm_events)
    for result in refinements:
        raw_events.extend(result.raw_llm_events)

    progress.log("Writing JSON reports and LLM trace.")
    (output_dir / "plans.json").write_text(
        json.dumps([plan.to_json() for plan in plans], indent=2),
        encoding="utf-8",
    )
    (output_dir / "baseline_validation.json").write_text(
        json.dumps([report.to_json() for report in baseline_reports], indent=2),
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
    _write_trace_outputs(output_dir, backend_result.traces, raw_events, baseline_reports, refined_reports)

    progress.log("Exporting PNG previews and gallery.")
    successful_prompts = [item for item in prompts if item.id in {artifact.id for artifact in refined_artifacts}]
    summary = export_artifacts(
        output_dir=output_dir,
        prompts=successful_prompts,
        baseline_artifacts=artifacts,
        refined_artifacts=refined_artifacts,
        baseline_reports=baseline_reports,
        refined_reports=refined_reports,
        refinements=refinements,
    )
    progress.log("Pipeline complete.")
    valid_count = sum(report.is_valid for report in baseline_reports)
    refined_valid_count = sum(report.is_valid for report in refined_reports)
    print(
        f"Generated {len(artifacts)} baseline SVG icons in {baseline_dir}. "
        f"Backend={backend_result.active_backend}. "
        f"LLM validator accepted {valid_count}/{len(baseline_reports)} baseline and "
        f"{refined_valid_count}/{len(refined_reports)} refined icons. "
        f"Average score improved by {summary['average_score_delta']}."
    )
    return 0


def _load_input_prompts(args: argparse.Namespace) -> list[PromptItem]:
    if args.prompt:
        case_ids = split_case_ids(args.case_id)
        return load_prompts(args.prompt, case_ids=case_ids)
    if args.case_id:
        raise ValueError("--case-id can only be used with --prompt.")
    if args.list_cases:
        raise ValueError("--list-cases can only be used with --prompt.")
    if args.text:
        return [make_prompt_from_text(args.text)]
    prompt = input("Icon prompt: ").strip()
    return [make_prompt_from_text(prompt, source="interactive")]


def _print_prompt_cases(prompts: list[PromptItem]) -> None:
    for item in prompts:
        print(f"{item.id}\t{item.category}\t{item.prompt}")


def _merge_refinement_traces(
    trace_by_id: dict[str, BackendTrace],
    refinements: list[RefinementResult],
) -> None:
    for result in refinements:
        trace = trace_by_id.get(result.id)
        if trace is None:
            continue
        trace.validator_backend = result.agent_statuses.get("validator", "not-run")
        trace.refiner_backend = result.agent_statuses.get("refiner", "not-run")
        trace.usage.update(result.usage)
        trace.errors.extend(result.errors)


def _write_trace_outputs(
    output_dir: Path,
    traces: list[BackendTrace],
    raw_events: list[dict[str, object]],
    baseline_reports: list[object] | None = None,
    refined_reports: list[object] | None = None,
) -> None:
    baseline_by_id = {report.id: report for report in baseline_reports or []}
    refined_by_id = {report.id: report for report in refined_reports or []}
    (output_dir / "llm_trace.json").write_text(
        json.dumps(
            [
                trace.to_json(
                    baseline_report=baseline_by_id.get(trace.id),
                    refined_report=refined_by_id.get(trace.id),
                )
                for trace in traces
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "llm_raw_responses.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in raw_events),
        encoding="utf-8",
    )
