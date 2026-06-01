# Report and Presentation Notes

## Proposed title

SVG Icon Agent: A Fully LLM-Backed Planning-Validation-Refinement Pipeline for Editable Vector Icon Generation

## Abstract draft

This project presents SVG Icon Agent, a lightweight multi-agent pipeline that converts short English icon prompts into editable SVG icons. Instead of relying on heavy diffusion or video models, every named Agent calls OpenRouter's `openai/gpt-oss-120b:free` model: planning, SVG drafting, validation, and refinement are all model-backed. Deterministic local code is restricted to prompt loading, machine-checkable SVG safety checks, PNG rendering, and report export. The pipeline produces baseline and refined SVG files, PNG previews, a gallery page, LLM trace logs, raw response logs, and quantitative metrics.

Code link: TODO

## Method section outline

- OpenRouter Planner Agent: asks `openai/gpt-oss-120b:free` for structured icon-plan JSON compatible with the local `IconPlan` data model.
- OpenRouter SVG Generator Agent: asks the model for a constrained SVG draft using only safe primitives.
- OpenRouter Validator Agent: asks the model to judge semantic alignment, visual quality, editability, and rule compliance, using local `SvgCheckTool` output as evidence.
- OpenRouter Refiner Agent: asks the model to return a complete repaired SVG based on validator and tool feedback.
- Local SvgCheckTool: checks parseability, canvas size, `viewBox`, unsafe tags, external references, accessible metadata, primitive count, and palette usage. It is a tool, not an Agent.
- Gallery Exporter: creates PNG previews, metrics, `llm_trace.json`, and a side-by-side HTML gallery for presentation.

## Experiment design

- Dataset: 12 manually written English prompts.
- Categories: 4 UI icons, 4 object icons, 4 scene icons.
- Inputs: full local prompt set, selected local cases, a manual `--text` prompt, or `--interactive` prompt entry.
- Baseline: first-pass SVG from the OpenRouter SVG Generator Agent.
- Refined: SVG after up to 3 OpenRouter Refiner Agent rounds.
- Metrics: LLM validation rate, average validation score, average score delta, max repair rounds, stage status, errors, and OpenRouter usage.

## Current result snapshot

- Total prompts: 12
- Baseline valid icons: TODO after OpenRouter run
- Refined valid icons: TODO after OpenRouter run
- Baseline average score: TODO after OpenRouter run
- Refined average score: TODO after OpenRouter run
- Average score delta: TODO after OpenRouter run
- Max repair rounds used: TODO after OpenRouter run
- OpenRouter model: `openai/gpt-oss-120b:free`
- Manual smoke test: run `OPENROUTER_API_KEY=... .venv/bin/python main.py --prompt prompts/examples.json --out outputs --backend openrouter`

## Innovation points

- Uses an LLM-assisted agentic workflow for vector graphics, not raster image generation.
- Keeps every named Agent model-backed, while local checks act only as deterministic tools.
- Makes failures inspectable through explicit validator issue codes and raw response logs.
- Produces editable SVG artifacts, which are easier to revise than bitmap outputs.
- Supports both repeatable local prompt cases and live manual input for demos.

## Suggested presentation flow

1. Problem: text-to-image models are overpowered for simple editable icons and are hard to control.
2. Idea: convert icon generation into LLM planning, constrained SVG drafting, LLM validation, and LLM repair.
3. System diagram: prompt to OpenRouter plan to baseline SVG to LLM validation report to refined SVG.
4. Demo: open `outputs/gallery.html` and `outputs/llm_trace.json`.
5. Results: show validity, score improvements, stage traces, and repair examples.
6. Limitations: free API may be rate-limited; renderer supports a practical SVG subset.
7. Future work: richer layout grammar, human preference evaluation, and more LLM-based repair strategies.

## References to cite

- GenPilot: multi-agent prompt optimization for image generation.
- Paper2Poster: multimodal poster automation from scientific papers.
- PosterForest: hierarchical multi-agent collaboration for poster generation.
- W3C SVG specification or MDN SVG documentation.
- OpenRouter API documentation.
- Pillow documentation for the lightweight PNG export implementation.
