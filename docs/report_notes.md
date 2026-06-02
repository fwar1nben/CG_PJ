# Report and Presentation Notes

## Proposed title

SVG Icon Agent: A Collaborative LLM-Agent Pipeline for Editable SVG Icon Generation

## Abstract draft

This project presents SVG Icon Agent, a lightweight collaborative multi-agent pipeline that converts short English icon prompts into editable SVG icons. Instead of relying on heavy diffusion or video models, every named Agent calls OpenRouter's `openai/gpt-oss-120b:free` model. The default workflow rewrites the user prompt for SVG-icon generation, plans the icon, generates multiple SVG candidates, asks separate semantic and SVG-quality Critic Agents to review them, uses a Consensus Selector Agent to choose the strongest draft, and then validates and refines the selected SVG. Deterministic local code is restricted to prompt loading, machine-checkable SVG safety checks, PNG rendering, and report export. The pipeline produces candidate, baseline, and refined SVG files, PNG previews, a gallery page, LLM trace logs, raw response logs, and quantitative metrics.

Code link: TODO

## Method section outline

- OpenRouter Prompt Rewriter Agent: rewrites the raw user prompt into a concise SVG-icon prompt while preserving explicit user intent.
- OpenRouter Planner Agent: asks `openai/gpt-oss-120b:free` for structured icon-plan JSON compatible with the local `IconPlan` data model.
- OpenRouter Multi-Candidate Generator Agent: asks the model for 3 distinct constrained SVG drafts using only safe primitives.
- OpenRouter Semantic Critic Agent: scores candidates for prompt alignment, recognizability, and small-icon readability.
- OpenRouter SVG Quality Critic Agent: scores candidates for editability, safety, rendering risk, and local `SvgCheckTool` issues.
- OpenRouter Consensus Selector Agent: chooses a winning candidate and writes a repair brief for the Refiner Agent.
- OpenRouter Validator Agent: asks the model to judge semantic alignment, visual quality, editability, and rule compliance, using local `SvgCheckTool` output as evidence.
- OpenRouter Refiner Agent: asks the model to return a complete repaired SVG based on validator and tool feedback.
- Local SvgCheckTool: checks parseability, canvas size, `viewBox`, unsafe tags, external references, accessible metadata, primitive count, and palette usage. It is a tool, not an Agent.
- Gallery Exporter: creates PNG previews, metrics, `llm_trace.json`, and a side-by-side HTML gallery for presentation.

## Experiment design

- Dataset: 12 manually written English prompts.
- Categories: 4 UI icons, 4 object icons, 4 scene icons.
- Inputs: full local prompt set, selected local cases, a manual `--text` prompt, or `--interactive` prompt entry.
- Baseline: selected winner from the multi-candidate Generator/Critic/Selector workflow.
- Refined: SVG after up to 3 OpenRouter Refiner Agent rounds.
- Ablation baseline: `--workflow single`, which skips candidate competition and critic/selector collaboration.
- Metrics: prompt rewrite trace, LLM validation rate, average validation score, average score delta, max repair rounds, candidate scores, selected candidate, critic scores, stage status, errors, and OpenRouter usage.

## Current result snapshot

- Total prompts: 12
- Baseline valid icons: TODO after OpenRouter run
- Refined valid icons: TODO after OpenRouter run
- Baseline average score: TODO after OpenRouter run
- Refined average score: TODO after OpenRouter run
- Average score delta: TODO after OpenRouter run
- Max repair rounds used: TODO after OpenRouter run
- OpenRouter model: `openai/gpt-oss-120b:free`
- Manual smoke test: run `OPENROUTER_API_KEY=... .venv/bin/python main.py --prompt prompts/examples.json --out outputs --backend openrouter --workflow collaborative --candidate-count 3`
- Ablation run: `OPENROUTER_API_KEY=... .venv/bin/python main.py --prompt prompts/examples.json --out outputs_single --backend openrouter --workflow single`

## Innovation points

- Uses an LLM-assisted agentic workflow for vector graphics, not raster image generation.
- Keeps every named Agent model-backed, while local checks act only as deterministic tools.
- Adds a Prompt Rewriter Agent before planning, making raw user input optimization visible and ablatable.
- Adds multi-candidate generation with independent semantic and SVG-quality Critic Agents.
- Uses a Consensus Selector Agent to make the final baseline choice explainable.
- Supports single-workflow ablation to compare direct generation against collaborative agent selection.
- Makes failures inspectable through explicit validator issue codes and raw response logs.
- Produces editable SVG artifacts, which are easier to revise than bitmap outputs.
- Supports both repeatable local prompt cases and live manual input for demos.

## Suggested presentation flow

1. Problem: text-to-image models are overpowered for simple editable icons and are hard to control.
2. Idea: convert icon generation into LLM prompt rewriting, planning, candidate drafting, independent critique, consensus selection, validation, and repair.
3. System diagram: raw prompt to rewritten prompt to OpenRouter plan to 3 candidates to semantic/SVG-quality critics to selector to refined SVG.
4. Demo: use the Web UI to show original vs rewritten prompt, candidate drafts, selected winner, trace, raw LLM responses, and final PNG.
5. Results: compare collaborative mode with `--workflow single`, showing validity, score improvements, selected candidates, and repair examples.
6. Limitations: free API may be rate-limited; renderer supports a practical SVG subset.
7. Future work: richer layout grammar, human preference evaluation, and more LLM-based repair strategies.

## References to cite

- GenPilot: multi-agent prompt optimization for image generation.
- Paper2Poster: multimodal poster automation from scientific papers.
- PosterForest: hierarchical multi-agent collaboration for poster generation.
- W3C SVG specification or MDN SVG documentation.
- OpenRouter API documentation.
- Pillow documentation for the lightweight PNG export implementation.
