# Report and Presentation Notes

## Proposed title

SVG Icon Agent: A Collaborative LLM-Agent Pipeline for Editable SVG Icon Generation

## Abstract draft

This project presents SVG Icon Agent, a lightweight collaborative multi-agent pipeline that converts short English icon prompts into editable SVG icons. Instead of relying on heavy diffusion or video models, every named Agent calls the configured LLM provider.
The current experiments use `openai/gpt-oss-120b:free` through OpenRouter.
The default workflow retrieves similar historical runs, creates a structured generation goal, rewrites the user prompt for SVG-icon generation, plans the icon, generates multiple SVG candidates, asks separate semantic and SVG-quality Critic Agents to review them, uses a Consensus Selector Agent to choose the strongest draft, asks an SVG Optimizer Agent to improve the selected draft from team feedback, validates the optimized SVG, routes blocking failures through Failure Taxonomy and Repair Router Agents, refines only when needed, and finally curates a reusable memory for future runs.
Deterministic local code is restricted to prompt loading, memory retrieval, machine-checkable SVG safety checks, PNG rendering, and report export. The pipeline produces goal, memory, candidate, selected, baseline, and refined SVG files, failure taxonomy and repair route logs, PNG previews, a gallery page, LLM trace logs, raw response logs, and quantitative metrics.

Code link: TODO

## Method section outline

- Local MemoryRetrievalTool: retrieves similar historical runs from local memory records. It is a tool, not an Agent.
- Goal Manager Agent: converts the user prompt, optional manual goal, and retrieved memories into objective, visual requirements, constraints, acceptance criteria, preferences, and avoid patterns.
- Prompt Rewriter Agent: rewrites the raw user prompt into a concise SVG-icon prompt while preserving explicit user intent.
- Planner Agent: asks the configured model for structured icon-plan JSON compatible with the local `IconPlan` data model.
- Multi-Candidate Generator Agent: asks the model for 3 distinct constrained SVG drafts using only safe primitives.
- Semantic Critic Agent: scores candidates for prompt alignment, recognizability, and small-icon readability.
- SVG Quality Critic Agent: scores candidates for editability, safety, rendering risk, and local `SvgCheckTool` issues.
- Consensus Selector Agent: chooses a winning candidate and writes a repair brief for downstream repair.
- SVG Optimizer Agent: improves the selected winner before validation using Critic reports, Selector risks and repair brief, `SvgCheckTool` output, and optional manual feedback.
- Post-run manual optimization: after the first pipeline finishes in the Web UI, the user can add new improvement advice and trigger another SVG Optimizer pass on the latest generated SVG, followed by Validator/Refiner/export.
- Validator Agent: asks the model to judge semantic alignment, visual quality, editability, and rule compliance, using local `SvgCheckTool` output as evidence.
- Failure Taxonomy Agent: classifies blocking validation issues into failure types, root causes, evidence, priority, and repair goals.
- Repair Router Agent: converts the taxonomy into a route, ordered actions, risk notes, and a concrete brief for the Refiner Agent.
- Refiner Agent: asks the model to return a complete repaired SVG based on validator, tool, taxonomy, and routing feedback.
- Memory Curator Agent: summarizes each completed run into reusable local memory containing successful strategies, failure patterns, user feedback, score, and tags.
- Local SvgCheckTool: checks parseability, canvas size, `viewBox`, unsafe tags, external references, accessible metadata, primitive count, and palette usage. It is a tool, not an Agent.
- Gallery Exporter: creates PNG previews, metrics, `llm_trace.json`, and a side-by-side HTML gallery for presentation.

## Experiment design

- Dataset: 12 manually written English prompts.
- Categories: 4 UI icons, 4 object icons, 4 scene icons.
- Inputs: full local prompt set, selected local cases, a manual `--text` prompt, or `--interactive` prompt entry.
- Selected: raw winner from the multi-candidate Generator/Critic/Selector workflow.
- Baseline: SVG Optimizer output after applying LLM team feedback and optional manual advice.
- Refined: SVG after up to 3 Refiner Agent rounds.
- Ablation baseline: `--workflow single`, which skips candidate competition and critic/selector collaboration.
- Metrics: generated goal, retrieved memory ids, prompt rewrite trace, optimizer feedback sources, failure types, repair routes, LLM validation rate, average validation score, average score delta, max repair rounds, candidate scores, selected candidate, critic scores, stage status, errors, and provider usage.

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
- Adds retrieval-augmented generation over local historical runs without using local SVG templates or local model fallback.
- Adds a Goal Manager Agent that makes generation objectives and acceptance criteria explicit before planning.
- Adds a Memory Curator Agent that converts completed runs into reusable future context.
- Adds a Prompt Rewriter Agent before planning, making raw user input optimization visible and ablatable.
- Adds multi-candidate generation with independent semantic and SVG-quality Critic Agents.
- Uses a Consensus Selector Agent to make the final baseline choice explainable.
- Adds an SVG Optimizer Agent that turns other agents' critiques, selector risks, deterministic tool checks, and optional human feedback into a revised SVG before validation.
- Adds a Failure Taxonomy Agent and Repair Router Agent, making repair explainable as diagnosis plus strategy instead of a generic retry.
- Supports human-in-the-loop post-run optimization, so the demo can show iterative user feedback without rerunning planning and candidate generation.
- Supports single-workflow ablation to compare direct generation against collaborative agent selection.
- Makes failures inspectable through validator issue codes, taxonomy labels, routed repair actions, and raw response logs.
- Produces editable SVG artifacts, which are easier to revise than bitmap outputs.
- Supports both repeatable local prompt cases and live manual input for demos.

## Suggested presentation flow

1. Problem: text-to-image models are overpowered for simple editable icons and are hard to control.
2. Idea: convert icon generation into memory retrieval, LLM goal management, prompt rewriting, planning, candidate drafting, independent critique, consensus selection, validation, failure taxonomy, repair routing, repair, and memory curation.
3. System diagram: raw prompt to retrieved memories to generation goal to rewritten prompt to plan to 3 candidates to semantic/SVG-quality critics to selector to optimizer to validator to failure taxonomy to repair router to refined SVG to curated memory.
4. Demo: use the Web UI to show original vs rewritten prompt, generated goal, retrieved memories, candidate drafts, selected winner, optimized baseline, live Agent workflow highlighting, failure taxonomy/repair route trace, manual optimizer feedback, post-run feedback optimization, raw LLM responses, and final PNG.
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
