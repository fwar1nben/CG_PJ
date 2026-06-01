"""CLI wiring for the SVG Icon Agent pipeline."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate SVG icons from English prompts.")
    parser.add_argument("--prompt", required=True, help="Path to a JSON prompt list.")
    parser.add_argument("--out", default="outputs", help="Output directory.")
    parser.add_argument("--max-refine-rounds", type=int, default=3, help="Maximum repair rounds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    print(f"SVG Icon Agent is ready. prompts={args.prompt} out={args.out}")
    return 0

