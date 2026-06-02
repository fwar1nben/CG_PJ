"""CLI wiring for the SVG Icon Agent pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL
from svg_icon_agent.pipeline import run_prompt_pipeline
from svg_icon_agent.progress import ProgressLogger
from svg_icon_agent.prompts import load_prompts, make_prompt_from_text, split_case_ids


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
        "--max-tokens",
        type=int,
        default=None,
        help="Optional max_tokens override for each OpenRouter agent request.",
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
    progress = ProgressLogger(verbose=not args.quiet)
    result = run_prompt_pipeline(
        prompts,
        output_dir=output_dir,
        model=args.model,
        max_refine_rounds=args.max_refine_rounds,
        request_timeout=args.request_timeout,
        max_retries=args.max_retries,
        max_tokens=args.max_tokens,
        progress=progress,
    )
    if result.status != "completed":
        print(f"{result.error or 'Pipeline failed.'} See llm_trace.json and llm_raw_responses.jsonl for details.")
        return 1

    baseline_dir = output_dir / "baseline"
    valid_count = sum(report.is_valid for report in result.baseline_reports)
    refined_valid_count = sum(report.is_valid for report in result.refined_reports)
    print(
        f"Generated {len(result.baseline_artifacts)} baseline SVG icons in {baseline_dir}. "
        f"Backend=openrouter. "
        f"LLM validator accepted {valid_count}/{len(result.baseline_reports)} baseline and "
        f"{refined_valid_count}/{len(result.refined_reports)} refined icons. "
        f"Average score improved by {result.summary['average_score_delta']}."
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
