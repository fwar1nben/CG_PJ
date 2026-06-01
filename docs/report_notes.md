# Report and Presentation Notes

## Proposed title

SVG Icon Agent: An OpenRouter-Assisted Planning-Validation-Refinement Pipeline for Editable Vector Icon Generation

## Abstract draft

This project presents SVG Icon Agent, a lightweight multi-agent pipeline that converts short English icon prompts into editable SVG icons. Instead of relying on heavy diffusion or video models, the system uses OpenRouter's `openai/gpt-oss-120b:free` model for icon planning and optional SVG drafting, then applies deterministic validation, fallback, and automatic refinement. The pipeline produces baseline and refined SVG files, PNG previews, a gallery page, LLM trace logs, and quantitative metrics. The current experiment uses 12 prompts across UI, object, and scene icons. In deterministic rule mode, all refined icons pass the validation rules in the current implementation.

Code link: TODO

## Method section outline

- OpenRouter Planner Agent: asks `openai/gpt-oss-120b:free` for structured icon-plan JSON compatible with the local `IconPlan` data model.
- OpenRouter SVG Generator Agent: asks the model for a constrained SVG draft using only safe primitives.
- Rule fallback agents: preserve deterministic planning and SVG generation when the API is unavailable, malformed, or invalid.
- Validator Agent: checks parseability, canvas size, `viewBox`, unsafe tags, external references, accessible metadata, primitive count, and palette usage.
- Refiner Agent: repairs issue codes from the validator, especially missing `viewBox`, `title`, and `desc`.
- Gallery Exporter: creates PNG previews, metrics, `llm_trace.json`, and a side-by-side HTML gallery for presentation.

## Experiment design

- Dataset: 12 manually written English prompts.
- Categories: 4 UI icons, 4 object icons, 4 scene icons.
- Baseline: first-pass SVG from either OpenRouter or the deterministic fallback generator.
- Refined: SVG after up to 3 repair rounds.
- Metrics: validity rate, average validation score, average score delta, max repair rounds, backend used, fallback reason, and OpenRouter usage.

## Current result snapshot

- Total prompts: 12
- Baseline valid icons: 0 / 12
- Refined valid icons: 12 / 12
- Baseline average score: 59.0
- Refined average score: 100.0
- Average score delta: 41.0
- Max repair rounds used: 1
- OpenRouter model: `openai/gpt-oss-120b:free`
- Manual smoke test: run `OPENROUTER_API_KEY=... .venv/bin/python main.py --prompt prompts/examples.json --out outputs --backend openrouter`

## Innovation points

- Uses an LLM-assisted agentic workflow for vector graphics, not raster image generation.
- Makes failures inspectable through explicit validator issue codes.
- Produces editable SVG artifacts, which are easier to revise than bitmap outputs.
- Keeps deterministic fallback behavior so the demo remains reproducible when the free model is rate-limited.

## Suggested presentation flow

1. Problem: text-to-image models are overpowered for simple editable icons and are hard to control.
2. Idea: convert icon generation into LLM planning, constrained SVG drafting, validation, fallback, and repair.
3. System diagram: prompt to OpenRouter/rule plan to baseline SVG to validation report to refined SVG.
4. Demo: open `outputs/gallery.html` and `outputs/llm_trace.json`.
5. Results: show validity, score improvements, backend traces, and fallback examples.
6. Limitations: free API may be rate-limited; renderer supports a practical SVG subset.
7. Future work: richer layout grammar, human preference evaluation, and more LLM-based repair strategies.

## References to cite

- GenPilot: multi-agent prompt optimization for image generation.
- Paper2Poster: multimodal poster automation from scientific papers.
- PosterForest: hierarchical multi-agent collaboration for poster generation.
- W3C SVG specification or MDN SVG documentation.
- OpenRouter API documentation.
- Pillow documentation for the lightweight PNG export implementation.
