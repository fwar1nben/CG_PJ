# SVG Icon Agent

SVG Icon Agent is a lightweight text-to-SVG project for Computer Graphics Project 3.
It turns short English icon prompts into editable SVG icons through a deterministic
multi-agent pipeline: planning, generation, validation, refinement, and gallery export.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --prompt prompts/examples.json --out outputs
.venv/bin/python -m unittest discover -s tests
```

Generated SVG, PNG, JSON metrics, and an HTML gallery are written under `outputs/`.

Useful output files:

- `outputs/baseline/*.svg`: first-pass SVG icons.
- `outputs/refined/*.svg`: validator-repaired SVG icons.
- `outputs/png/baseline/*.png` and `outputs/png/refined/*.png`: raster previews.
- `outputs/gallery.html`: side-by-side visual comparison for the report and slides.
- `outputs/metrics.json`: aggregate validity and score improvements.
- `outputs/refinement_history.json`: per-icon repair logs.

## Pipeline

1. Planner Agent extracts icon intent, palette, category, objects, and constraints.
2. SVG Generator Agent creates a baseline icon using safe SVG primitives.
3. Validator Agent checks structure, dimensions, safety, and visual-rule compliance.
4. Refiner Agent repairs validation issues and exports the refined icon.
5. Gallery Exporter renders comparison artifacts for the report and presentation.

## Current experiment

The default experiment uses 12 English prompts across UI icons, object icons, and
small scene icons. The baseline generator intentionally leaves out some metadata
such as `viewBox`, `title`, and `desc`, so the refinement loop can demonstrate a
measurable repair process. In the current run, all 12 refined icons pass validation.

## Project positioning

This project avoids training large image models. Its graphics component is editable
SVG generation, while its agent component is a decomposed planning, generation,
validation, and self-repair loop. That keeps the system reproducible on free local
resources and makes the innovation easy to explain in the Project 3 report.

