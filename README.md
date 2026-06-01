# SVG Icon Agent

SVG Icon Agent is a lightweight text-to-SVG project for Computer Graphics Project 3.
It turns short English icon prompts into editable SVG icons through a hybrid
multi-agent pipeline: OpenRouter-backed planning/SVG drafting, deterministic
validation, automatic refinement, and gallery export.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --prompt prompts/examples.json --out outputs --backend rule
.venv/bin/python -m unittest discover -s tests
```

To use OpenRouter with `openai/gpt-oss-120b:free`, copy `.env.example` to `.env`
or export the variables in your shell:

```bash
export OPENROUTER_API_KEY="your-key"
export OPENROUTER_MODEL="openai/gpt-oss-120b:free"
.venv/bin/python main.py \
  --prompt prompts/examples.json \
  --out outputs \
  --backend openrouter \
  --request-timeout 30 \
  --max-retries 1
```

The default `--backend auto` uses OpenRouter when `OPENROUTER_API_KEY` is set and
falls back to the deterministic rule backend otherwise.

OpenRouter free models can be slow or queued. With the default `--llm-stage plan-svg`,
the system may make up to two model requests per prompt: one for planning and one
for SVG drafting. The command prints realtime progress for each stage. To halve
the number of model calls, use `--llm-stage plan`; the SVG will then be generated
by the deterministic rule backend from the LLM plan.

Generated SVG, PNG, JSON metrics, and an HTML gallery are written under `outputs/`.

Useful output files:

- `outputs/baseline/*.svg`: first-pass SVG icons.
- `outputs/refined/*.svg`: validator-repaired SVG icons.
- `outputs/png/baseline/*.png` and `outputs/png/refined/*.png`: raster previews.
- `outputs/gallery.html`: side-by-side visual comparison for the report and slides.
- `outputs/metrics.json`: aggregate validity and score improvements.
- `outputs/refinement_history.json`: per-icon repair logs.
- `outputs/llm_trace.json`: backend, model, usage, fallback reason, and score trace.

## Pipeline

1. Planner Agent extracts icon intent, palette, category, objects, and constraints.
   It can use OpenRouter or the deterministic rule planner.
2. SVG Generator Agent creates a baseline icon using safe SVG primitives. With
   `--llm-stage plan-svg`, OpenRouter drafts the SVG first.
3. Validator Agent checks structure, dimensions, safety, and visual-rule compliance.
4. Refiner Agent repairs validation issues and exports the refined icon.
5. Gallery Exporter renders comparison artifacts for the report and presentation.

## Current experiment

The default experiment uses 12 English prompts across UI icons, object icons, and
small scene icons. In rule mode, the baseline generator intentionally leaves out
some metadata such as `viewBox`, `title`, and `desc`, so the refinement loop can
demonstrate a measurable repair process. In the current rule run, all 12 refined
icons pass validation.

## Project positioning

This project avoids training large image models. Its graphics component is editable
SVG generation, while its agent component is a decomposed OpenRouter planning,
SVG drafting, validation, fallback, and self-repair loop. The rule backend keeps
the system reproducible when the free model is unavailable.

## CLI options

- `--backend rule|openrouter|auto`: choose deterministic rules, OpenRouter, or
  automatic backend selection.
- `--model`: OpenRouter model id, default `openai/gpt-oss-120b:free`.
- `--request-timeout`: per-request OpenRouter timeout in seconds.
- `--max-retries`: retry count for retryable OpenRouter failures.
- `--llm-stage plan|plan-svg`: use the LLM for planning only or for both planning
  and SVG drafting.
- `--max-refine-rounds`: maximum deterministic repair rounds after validation.
- `--quiet`: hide realtime progress logs.
