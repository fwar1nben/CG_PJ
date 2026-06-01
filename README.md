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

## Pipeline

1. Planner Agent extracts icon intent, palette, category, objects, and constraints.
2. SVG Generator Agent creates a baseline icon using safe SVG primitives.
3. Validator Agent checks structure, dimensions, safety, and visual-rule compliance.
4. Refiner Agent repairs validation issues and exports the refined icon.
5. Gallery Exporter renders comparison artifacts for the report and presentation.

