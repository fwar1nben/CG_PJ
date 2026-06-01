# Report and Presentation Notes

## Proposed title

SVG Icon Agent: A Lightweight Planning-Validation-Refinement Pipeline for Editable Vector Icon Generation

## Abstract draft

This project presents SVG Icon Agent, a lightweight multi-agent pipeline that converts short English icon prompts into editable SVG icons. Instead of relying on heavy diffusion or video models, the system decomposes the task into planning, deterministic SVG generation, rule-based validation, and automatic refinement. The pipeline produces baseline and refined SVG files, PNG previews, a gallery page, and quantitative metrics. The current experiment uses 12 prompts across UI, object, and scene icons. Baseline outputs are intentionally checked by the validator, then repaired by the refiner; all refined icons pass the validation rules in the current implementation.

Code link: TODO

## Method section outline

- Planner Agent: extracts category, style, palette, motifs, layout, and constraints from each prompt.
- SVG Generator Agent: maps the plan to safe SVG primitives such as `rect`, `circle`, `path`, `line`, `polyline`, and `polygon`.
- Validator Agent: checks parseability, canvas size, `viewBox`, unsafe tags, external references, accessible metadata, primitive count, and palette usage.
- Refiner Agent: repairs issue codes from the validator, especially missing `viewBox`, `title`, and `desc`.
- Gallery Exporter: creates PNG previews, metrics, and a side-by-side HTML gallery for presentation.

## Experiment design

- Dataset: 12 manually written English prompts.
- Categories: 4 UI icons, 4 object icons, 4 scene icons.
- Baseline: first-pass deterministic SVG from the generator.
- Refined: SVG after up to 3 repair rounds.
- Metrics: validity rate, average validation score, average score delta, max repair rounds.

## Current result snapshot

- Total prompts: 12
- Baseline valid icons: 0 / 12
- Refined valid icons: 12 / 12
- Baseline average score: 59.0
- Refined average score: 100.0
- Average score delta: 41.0
- Max repair rounds used: 1

## Innovation points

- Uses an agentic workflow for vector graphics, not raster image generation.
- Makes failures inspectable through explicit validator issue codes.
- Produces editable SVG artifacts, which are easier to revise than bitmap outputs.
- Runs locally with a small Python environment and does not require model training.

## Suggested presentation flow

1. Problem: text-to-image models are overpowered for simple editable icons and are hard to control.
2. Idea: convert icon generation into planning, SVG code generation, validation, and repair.
3. System diagram: prompt to plan to baseline SVG to validation report to refined SVG.
4. Demo: open `outputs/gallery.html` and show baseline/refined comparisons.
5. Results: show validity and score improvements.
6. Limitations: deterministic templates are limited; renderer supports a practical SVG subset.
7. Future work: add LLM-backed planning, richer layout grammar, and human preference evaluation.

## References to cite

- GenPilot: multi-agent prompt optimization for image generation.
- Paper2Poster: multimodal poster automation from scientific papers.
- PosterForest: hierarchical multi-agent collaboration for poster generation.
- W3C SVG specification or MDN SVG documentation.
- Pillow documentation for the lightweight PNG export implementation.

