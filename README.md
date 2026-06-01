# SVG Icon Agent

SVG Icon Agent is a lightweight text-to-SVG project for Computer Graphics Project 3.
It turns short English icon prompts into editable SVG icons through a fully
LLM-backed multi-agent pipeline: OpenRouter planning, SVG drafting, validation,
refinement, and gallery export. Local code is limited to prompt loading,
machine-checkable SVG safety checks, rendering, and reporting tools.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
```

Use OpenRouter with `openai/gpt-oss-120b:free` by copying `.env.example` to
`.env` or exporting the variables in your shell:

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

Manual input is also supported:

```bash
.venv/bin/python main.py --text "a minimal rocket launch icon with a blue flame" --out outputs/manual
.venv/bin/python main.py --interactive --out outputs/manual
.venv/bin/python main.py --prompt prompts/examples.json --list-cases
.venv/bin/python main.py --prompt prompts/examples.json --case-id object-rocket,object-coffee-cup --out outputs/selected
```

OpenRouter free models can be slow or queued. The pipeline makes model calls for
planning, SVG drafting, LLM validation, and LLM refinement when repairs are needed.
The command prints realtime progress for each stage. If a model call fails, the
error is logged; the system does not synthesize a local SVG fallback.

Generated SVG, PNG, JSON metrics, and an HTML gallery are written under `outputs/`.

Useful output files:

- `outputs/baseline/*.svg`: first-pass SVG icons.
- `outputs/refined/*.svg`: LLM-refined SVG icons.
- `outputs/png/baseline/*.png` and `outputs/png/refined/*.png`: raster previews.
- `outputs/gallery.html`: side-by-side visual comparison for the report and slides.
- `outputs/metrics.json`: aggregate validity and score improvements.
- `outputs/refinement_history.json`: per-icon repair logs.
- `outputs/llm_trace.json`: model usage, stage status, errors, and score trace.
- `outputs/llm_raw_responses.jsonl`: sanitized raw OpenRouter responses and error payloads.

## Pipeline

1. Planner Agent extracts icon intent, palette, category, objects, and constraints.
   This Agent calls OpenRouter.
2. SVG Generator Agent creates a baseline icon using safe SVG primitives.
   This Agent calls OpenRouter.
3. Validator Agent judges semantic alignment, visual quality, editability, and
   rule compliance. This Agent calls OpenRouter and receives local `SvgCheckTool`
   findings as evidence.
4. Refiner Agent repairs validation issues by returning a complete revised SVG.
   This Agent calls OpenRouter.
5. Local tools render PNG previews, metrics, trace logs, and the gallery.

## Current experiment

The default experiment uses 12 English prompts across UI icons, object icons, and
small scene icons. The same pipeline also accepts selected cases, one manual
prompt, or one interactive prompt for live demos.

## Project positioning

This project avoids training large image models. Its graphics component is editable
SVG generation, while its agent component is a decomposed OpenRouter planning,
SVG drafting, validation, and self-repair loop. Deterministic local code is only
used as a toolchain for syntax/safety checks, rendering, and report export.

## CLI options

- `--prompt`: run local JSON prompt cases.
- `--case-id`: choose comma-separated cases from `--prompt`.
- `--list-cases`: list available prompt cases and exit.
- `--text`: run one manual prompt.
- `--interactive`: type one prompt interactively.
- `--backend openrouter`: use the OpenRouter LLM pipeline.
- `--model`: OpenRouter model id, default `openai/gpt-oss-120b:free`.
- `--request-timeout`: per-request OpenRouter timeout in seconds.
- `--max-retries`: retry count for retryable OpenRouter failures.
- `--llm-stage plan-svg`: the LLM performs both planning and SVG drafting.
- `--max-refine-rounds`: maximum LLM repair rounds after validation.
- `--quiet`: hide realtime progress logs.
