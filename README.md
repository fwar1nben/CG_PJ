# SVG Icon Agent

SVG Icon Agent is a lightweight text-to-SVG project for Computer Graphics Project 3.
It turns short English icon prompts into editable SVG icons through a fully
LLM-backed multi-agent pipeline: OpenRouter planning, multi-candidate SVG
drafting, semantic and SVG-quality critique, consensus selection, validation,
refinement, and gallery export. A Prompt Rewriter Agent first optimizes the
input description for SVG icon generation. Local code is limited to prompt loading,
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
  --max-retries 1 \
  --empty-response-retries 3 \
  --max-tokens 4096 \
  --reasoning-effort none \
  --workflow collaborative \
  --candidate-count 3
```

Manual input is also supported:

```bash
.venv/bin/python main.py --text "a minimal rocket launch icon with a dynamic flame" --out outputs/manual
.venv/bin/python main.py --interactive --out outputs/manual
.venv/bin/python main.py --prompt prompts/examples.json --list-cases
.venv/bin/python main.py --prompt prompts/examples.json --case-id object-rocket,object-coffee-cup --out outputs/selected
```

OpenRouter free models can be slow or queued. The pipeline makes model calls for
planning, candidate SVG drafting, LLM critique, consensus selection, validation,
and LLM refinement when repairs are needed. The default workflow also rewrites
the prompt before planning.
The command prints realtime progress for each stage. If a model call fails, the
error is logged; the system does not synthesize a local SVG fallback.

Generated SVG, PNG, JSON metrics, and an HTML gallery are written under `outputs/`.

Useful output files:

- `outputs/baseline/*.svg`: first-pass SVG icons.
- `outputs/candidates/*.svg`: candidate drafts from collaborative mode.
- `outputs/refined/*.svg`: LLM-refined SVG icons.
- `outputs/png/baseline/*.png` and `outputs/png/refined/*.png`: raster previews.
- `outputs/gallery.html`: side-by-side visual comparison for the report and slides.
- `outputs/metrics.json`: aggregate validity and score improvements.
- `outputs/refinement_history.json`: per-icon repair logs.
- `outputs/llm_trace.json`: model usage, stage status, errors, and score trace.
- `outputs/llm_raw_responses.jsonl`: sanitized raw OpenRouter responses and error payloads.

## Pipeline

1. Prompt Rewriter Agent rewrites the user prompt into a concise SVG-icon prompt.
   This Agent calls OpenRouter.
2. Planner Agent extracts icon intent, palette, category, objects, and constraints.
   This Agent calls OpenRouter.
3. Multi-Candidate Generator Agent creates several different SVG drafts.
   This Agent calls OpenRouter.
4. Semantic Critic Agent judges prompt alignment and small-icon readability.
   This Agent calls OpenRouter.
5. SVG Quality Critic Agent judges editability, safety, and rendering risk using
   local `SvgCheckTool` findings as evidence. This Agent calls OpenRouter.
6. Consensus Selector Agent chooses the strongest candidate and writes a repair
   brief for the next Agent. This Agent calls OpenRouter.
7. Validator Agent judges semantic alignment, visual quality, editability, and
   rule compliance. This Agent calls OpenRouter and receives local `SvgCheckTool`
   findings as evidence.
8. Refiner Agent repairs validation issues by returning a complete revised SVG.
   This Agent calls OpenRouter.
9. Local tools render PNG previews, metrics, trace logs, and the gallery.

## Current experiment

The default experiment uses collaborative mode with 3 candidates per prompt over
12 English prompts across UI icons, object icons, and small scene icons. Use
`--workflow single` for a faster ablation baseline. The same pipeline also
accepts selected cases, one manual prompt, or one interactive prompt for live
demos.

## Project positioning

This project avoids training large image models. Its graphics component is editable
SVG generation, while its agent component is a decomposed OpenRouter planning,
candidate generation, critique, selection, validation, and self-repair loop.
Deterministic local code is only used as a toolchain for syntax/safety checks,
rendering, and report export.

## CLI options

- `--prompt`: run local JSON prompt cases.
- `--case-id`: choose comma-separated cases from `--prompt`.
- `--list-cases`: list available prompt cases and exit.
- `--text`: run one manual prompt.
- `--interactive`: type one prompt interactively.
- `--backend openrouter`: use the OpenRouter LLM pipeline.
- `--model`: OpenRouter model id, default `openai/gpt-oss-120b:free`.
- `--workflow`: `collaborative` by default; use `single` for ablation.
- `--candidate-count`: number of SVG candidates in collaborative mode, default 3.
- `--no-prompt-rewrite`: disable Prompt Rewriter Agent for ablation.
- `--request-timeout`: per-request OpenRouter timeout in seconds.
- `--max-retries`: retry count for retryable OpenRouter failures.
- `--empty-response-retries`: retry count for empty model messages, default 3.
- `--max-tokens`: optional `max_tokens` override for each OpenRouter Agent request.
- `--reasoning-effort`: OpenRouter reasoning effort, default `none`.
- `--reasoning-max-tokens`: optional reasoning token cap; takes precedence over effort.
- `--llm-stage plan-svg`: the LLM performs both planning and SVG drafting.
- `--max-refine-rounds`: maximum LLM repair rounds after validation.
- `--quiet`: hide realtime progress logs.
