"""Pipeline checks for the SVG Icon Agent."""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from svg_icon_agent.backends import generate_with_backend
from svg_icon_agent.cli import main
from svg_icon_agent.exporter import render_svg_to_png
from svg_icon_agent.llm_agents import (
    ConsensusSelectorAgent,
    GoalManagerAgent,
    MemoryCuratorAgent,
    MultiCandidateGeneratorAgent,
    PlannerAgent,
    PromptRewriterAgent,
    RefinerAgent,
    SemanticCriticAgent,
    SvgGeneratorAgent,
    SvgOptimizerAgent,
    SvgQualityCriticAgent,
    ValidatorAgent,
)
from svg_icon_agent.openrouter_client import OpenRouterClient, OpenRouterConfig, OpenRouterError, OpenRouterResponse
from svg_icon_agent.models import SvgArtifact
from svg_icon_agent.memory import MemoryRetrievalTool, MemoryRecord
from svg_icon_agent.pipeline import make_reasoning_config
from svg_icon_agent.prompts import load_prompts, make_prompt_from_text
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.svg_check_tool import SvgCheckTool
from svg_icon_agent.web_app import create_app


PROMPT_PATH = Path("prompts/examples.json")


VALID_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>Cloud Download</title>
  <desc>Cloud download icon</desc>
  <rect x="20" y="20" width="216" height="216" rx="40" fill="#dbeafe"/>
  <circle cx="95" cy="126" r="36" fill="white" stroke="#111827" stroke-width="8"/>
  <circle cx="134" cy="112" r="44" fill="white" stroke="#111827" stroke-width="8"/>
  <line x1="128" y1="91" x2="128" y2="172" stroke="#2563eb" stroke-width="12"/>
  <polyline points="101,145 128,174 155,145" fill="none" stroke="#2563eb" stroke-width="12"/>
</svg>"""


class FakeOpenRouterClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("FakeOpenRouterClient has no remaining responses.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeHttpResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeHttpSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("FakeHttpSession has no remaining responses.")
        return self.responses.pop(0)


class BlockingAfterRewriteClient:
    def __init__(self, rewritten_prompt):
        self.rewritten_prompt = rewritten_prompt
        self.calls: list[dict[str, object]] = []
        self.rewrite_done = threading.Event()
        self.allow_continue = threading.Event()

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if len(self.calls) == 1:
            return _goal_response()
        if len(self.calls) == 2:
            self.rewrite_done.set()
            return _rewrite_response(self.rewritten_prompt)
        self.allow_continue.wait(timeout=2.0)
        raise OpenRouterError("planner intentionally stopped")


def _plan_response(item):
    return OpenRouterResponse(
        content=json.dumps(
            {
                "category": item.category,
                "style": item.style,
                "palette": list(item.palette),
                "motifs": ["cloud", "download"],
                "layout": "centered-symbol",
                "constraints": ["safe-svg-primitives-only"],
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        raw={"choices": [{"message": {"content": "plan-json"}}]},
    )


def _rewrite_response(text="a clear minimal cloud download icon with centered arrow and simple geometric silhouette"):
    return OpenRouterResponse(
        content=json.dumps({"rewritten_prompt": text}),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 18},
        raw={"choices": [{"message": {"content": "rewrite-json"}}]},
    )


def _goal_response():
    return OpenRouterResponse(
        content=json.dumps(
            {
                "objective": "Create a mobile-toolbar-ready cloud download icon.",
                "visual_requirements": ["clear arrow", "compact cloud"],
                "constraints": ["safe primitives", "readable at 32px"],
                "acceptance_criteria": ["valid svg", "recognizable download action"],
                "style_preferences": ["mixed"],
                "avoid_patterns": ["tiny details"],
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 28},
        raw={"choices": [{"message": {"content": "goal-json"}}]},
    )


def _memory_curator_response():
    return OpenRouterResponse(
        content=json.dumps(
            {
                "summary": "Large arrows and compact cloud silhouettes work well for download icons.",
                "success_patterns": ["large central arrow", "compact cloud"],
                "failure_patterns": ["small arrowhead"],
                "user_feedback": ["make the arrow stronger"],
                "score": 94,
                "tags": ["cloud", "download"],
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 35},
        raw={"choices": [{"message": {"content": "memory-json"}}]},
    )


def _svg_response(svg=VALID_SVG):
    return OpenRouterResponse(
        content=svg,
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 100},
        raw={"choices": [{"message": {"content": svg}}]},
    )


def _validation_response(valid=True, score=100, issues=None):
    return OpenRouterResponse(
        content=json.dumps(
            {
                "valid": valid,
                "score": score,
                "issues": issues or [],
                "semantic_alignment": "The SVG matches the prompt.",
                "aesthetic_notes": "The icon is readable.",
                "repair_brief": "No repair needed." if valid else "Repair unsafe or invalid SVG features.",
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 30},
        raw={"choices": [{"message": {"content": "validator-json"}}]},
    )


def _critique_response(candidate_ids, scores=None):
    scores = scores or [80 for _ in candidate_ids]
    return OpenRouterResponse(
        content=json.dumps(
            {
                "critiques": [
                    {
                        "candidate_id": candidate_id,
                        "score": scores[index],
                        "strengths": ["clear silhouette"],
                        "issues": [],
                        "recommendation": "Keep this candidate concise.",
                    }
                    for index, candidate_id in enumerate(candidate_ids)
                ]
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 40},
        raw={"choices": [{"message": {"content": "critic-json"}}]},
    )


def _selection_response(winner="candidate-2"):
    return OpenRouterResponse(
        content=json.dumps(
            {
                "winner_candidate_id": winner,
                "rationale": "It has the clearest symbol and safest structure.",
                "risks": ["minor details may need simplification"],
                "repair_brief": "Simplify details and preserve the selected silhouette.",
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 45},
        raw={"choices": [{"message": {"content": "selector-json"}}]},
    )


def _optimizer_response(svg=None):
    optimized_svg = svg or VALID_SVG.replace("Cloud Download", "Optimized Cloud Download")
    return OpenRouterResponse(
        content=optimized_svg,
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 110},
        raw={"choices": [{"message": {"content": optimized_svg}}]},
    )


def _failure_taxonomy_response():
    return OpenRouterResponse(
        content=json.dumps(
            {
                "failure_types": ["syntax_safety", "renderability"],
                "root_causes": ["unsafe script element"],
                "evidence": ["validator reported unsafe-tag", "tool report rejected script"],
                "priority": "critical",
                "repair_goals": ["remove unsafe element", "return safe editable svg"],
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 32},
        raw={"choices": [{"message": {"content": "taxonomy-json"}}]},
    )


def _repair_route_response(route="safety_rebuild"):
    return OpenRouterResponse(
        content=json.dumps(
            {
                "route": route,
                "strategy": "Rebuild the unsafe SVG with allowed editable primitives.",
                "ordered_actions": ["remove script", "restore 256 canvas", "preserve prompt semantics"],
                "refiner_brief": "Return a complete safe SVG with no scripts or external assets.",
                "risk_notes": ["avoid losing the main cloud download meaning"],
            }
        ),
        model="openai/gpt-oss-120b:free",
        usage={"completion_tokens": 38},
        raw={"choices": [{"message": {"content": "repair-route-json"}}]},
    )


def _collaborative_success_responses(item, winner="candidate-2"):
    candidate_ids = ["candidate-1", "candidate-2", "candidate-3"]
    return [
        _goal_response(),
        _rewrite_response(item.prompt),
        _plan_response(item),
        _svg_response(VALID_SVG),
        _svg_response(VALID_SVG.replace("Cloud Download", "Cloud Download Alt")),
        _svg_response(VALID_SVG.replace("Cloud Download", "Cloud Download Simple")),
        _critique_response(candidate_ids, scores=[72, 91, 84]),
        _critique_response(candidate_ids, scores=[80, 88, 82]),
        _selection_response(winner),
        _optimizer_response(),
        _validation_response(valid=True, score=100, issues=[]),
    ]


class PromptTests(unittest.TestCase):
    def test_examples_have_expected_coverage(self) -> None:
        prompts = load_prompts(PROMPT_PATH)

        self.assertEqual(len(prompts), 12)
        self.assertEqual({item.category for item in prompts}, {"ui", "object", "scene"})
        self.assertEqual(len({item.id for item in prompts}), 12)
        self.assertTrue(all(item.source.endswith("prompts/examples.json") for item in prompts))

    def test_case_selection_and_manual_prompt_input(self) -> None:
        selected = load_prompts(PROMPT_PATH, case_ids=["object-rocket", "object-coffee-cup"])
        manual = make_prompt_from_text("a minimal rocket launch icon with a dynamic flame")

        self.assertEqual([item.id for item in selected], ["object-coffee-cup", "object-rocket"])
        self.assertEqual(manual.source, "manual")
        self.assertIn("rocket", manual.id)


class LocalToolTests(unittest.TestCase):
    def test_local_svg_check_tool_is_not_named_agent(self) -> None:
        artifact = type("Artifact", (), {"id": "bad", "stage": "baseline", "svg": "<svg><script /></svg>"})()

        report = SvgCheckTool().check(artifact)

        self.assertFalse(report.is_valid)
        self.assertIn("unsafe-tag", {issue.code for issue in report.issues})

    def test_png_renderer_handles_llm_path_commands(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>Path Commands</title>
  <desc>Uses relative arc, horizontal, and quadratic path commands.</desc>
  <path d="M80 120 a40 40 0 0 1 80 0 h20 a30 30 0 0 1 0 60 h-120 a30 30 0 0 1 0 -60 z" fill="none" stroke="#2563eb" stroke-width="8"/>
  <path d="M70 210 q58 -40 116 0" fill="none" stroke="#111827" stroke-width="6"/>
</svg>"""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "preview.png"

            render_svg_to_png(svg, output)

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)

    def test_memory_retrieval_tool_indexes_and_retrieves_prior_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "outputs"
            rocket_run = root / "web" / "rocket-run"
            coffee_run = root / "web" / "coffee-run"
            rocket_run.mkdir(parents=True)
            coffee_run.mkdir(parents=True)
            (rocket_run / "plans.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "rocket",
                            "category": "object",
                            "prompt": "a minimal rocket launch icon with a dynamic flame",
                            "style": "mixed",
                            "palette": ["#111111", "#222222", "#333333"],
                            "motifs": ["rocket", "flame"],
                            "layout": "centered",
                            "constraints": ["simple"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (rocket_run / "llm_trace.json").write_text(
                json.dumps(
                    [
                        {
                            "selector_rationale": "clear upward rocket silhouette",
                            "post_run_optimizer_feedback": "make the flame larger",
                            "refined_score": 92,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (coffee_run / "plans.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "coffee",
                            "category": "object",
                            "prompt": "a simple coffee cup icon with steam",
                            "style": "line",
                            "palette": ["#111111", "#222222", "#333333"],
                            "motifs": ["coffee", "steam"],
                            "layout": "centered",
                            "constraints": ["simple"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            tool = MemoryRetrievalTool(root / "memory" / "memory_index.jsonl")
            records = tool.rebuild_from_outputs(root)
            context = tool.retrieve("rocket flame launch", top_k=1)

            self.assertEqual(len(records), 2)
            self.assertEqual(len(context.records), 1)
            self.assertIn("rocket", context.records[0].record.prompt)
            self.assertIn("make the flame larger", context.records[0].record.user_feedback)

    def test_memory_retrieval_tool_appends_curated_record_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "memory_index.jsonl"
            tool = MemoryRetrievalTool(index)
            record = MemoryRecord(
                id="mem-test",
                source_path="run",
                prompt="rocket icon",
                summary="use a strong silhouette",
                success_patterns=("large flame",),
            )

            tool.append_record(record)
            tool.append_record(record)

            self.assertEqual(len(tool.load_records()), 1)
            self.assertIn("large flame", tool.retrieve("rocket flame", top_k=1).records[0].record.success_patterns)


class OpenRouterAgentBoundaryTests(unittest.TestCase):
    def test_only_openrouter_classes_are_named_agents(self) -> None:
        for path in Path("svg_icon_agent").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "class " not in text:
                continue
            agent_classes = [line for line in text.splitlines() if line.startswith("class ") and "Agent" in line]
            if agent_classes:
                self.assertEqual(path.name, "llm_agents.py", agent_classes)

    def test_all_agent_constructors_require_openrouter_client(self) -> None:
        for cls in (
            PlannerAgent,
            GoalManagerAgent,
            MemoryCuratorAgent,
            PromptRewriterAgent,
            SvgGeneratorAgent,
            MultiCandidateGeneratorAgent,
            SemanticCriticAgent,
            SvgQualityCriticAgent,
            ConsensusSelectorAgent,
            SvgOptimizerAgent,
            ValidatorAgent,
            RefinerAgent,
        ):
            annotations = inspect.get_annotations(cls.__init__, eval_str=True)
            self.assertEqual(annotations["client"], OpenRouterClient)

    def test_hardcoded_rule_generator_module_was_removed(self) -> None:
        self.assertFalse(Path("svg_icon_agent/generator.py").exists())


class OpenRouterPipelineTests(unittest.TestCase):
    def test_openrouter_client_retries_empty_messages(self) -> None:
        empty = {
            "model": "test-model",
            "choices": [{"message": {"content": None}, "finish_reason": "length"}],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 4096}},
        }
        valid = {
            "model": "test-model",
            "choices": [{"message": {"content": "  <svg></svg>  "}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 4},
        }
        session = FakeHttpSession([FakeHttpResponse(empty), FakeHttpResponse(valid)])
        client = OpenRouterClient(
            OpenRouterConfig(
                api_key="test-key",
                model="test-model",
                max_retries=0,
                empty_response_retries=3,
            ),
            session=session,
        )

        response = client.chat([{"role": "user", "content": "make svg"}])

        self.assertEqual(response.content, "<svg></svg>")
        self.assertEqual(session.calls, 2)

    def test_openrouter_planner_json_converts_to_icon_plan(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient([_plan_response(item)])

        result = PlannerAgent(
            client,
            max_tokens=4096,
            reasoning=make_reasoning_config("none"),
        ).plan(item)

        self.assertEqual(result.plan.id, item.id)
        self.assertEqual(result.plan.category, "ui")
        self.assertIn("cloud", result.plan.motifs)
        self.assertIn("square-256-canvas", result.plan.constraints)
        self.assertEqual(result.response.usage["completion_tokens"], 20)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["kwargs"]["max_tokens"], 4096)
        self.assertEqual(client.calls[0]["kwargs"]["reasoning"], {"effort": "none", "exclude": True})

    def test_prompt_rewriter_converts_prompt_item(self) -> None:
        item = make_prompt_from_text("rocket")
        rewritten = "a minimal rocket launch icon with a clear centered silhouette and dynamic flame"
        client = FakeOpenRouterClient([_rewrite_response(rewritten)])

        result = PromptRewriterAgent(client).rewrite(item)

        self.assertEqual(result.item.id, item.id)
        self.assertEqual(result.item.prompt, rewritten)
        self.assertEqual(result.rewritten_prompt, rewritten)
        self.assertEqual(len(client.calls), 1)
        prompt_text = client.calls[0]["messages"][1]["content"]
        self.assertIn("35 to 60 words", prompt_text)
        self.assertIn("noticeably richer", prompt_text)
        self.assertIn("visual hierarchy", prompt_text)

    def test_goal_manager_creates_generation_goal(self) -> None:
        item = make_prompt_from_text("a cloud download icon")
        client = FakeOpenRouterClient([_goal_response()])

        result = GoalManagerAgent(client).create_goal(item, manual_goal="mobile toolbar")

        self.assertIn("mobile", result.goal.objective)
        self.assertIn("clear-arrow", result.goal.visual_requirements)
        self.assertIn("tiny-details", result.goal.avoid_patterns)
        prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("Manual goal", prompt)
        self.assertIn("mobile toolbar", prompt)

    def test_memory_curator_returns_short_record(self) -> None:
        item = make_prompt_from_text("a cloud download icon")
        plan_result = PlannerAgent(FakeOpenRouterClient([_plan_response(item)])).plan(item)
        goal = GoalManagerAgent(FakeOpenRouterClient([_goal_response()])).create_goal(item).goal
        client = FakeOpenRouterClient([_memory_curator_response()])

        result = MemoryCuratorAgent(client).curate(
            item,
            plan_result.plan,
            goal=goal,
            trace={"refined_score": 94, "selector_rationale": "clear arrow"},
            metrics={"refined_average_score": 94},
        )

        self.assertIn("compact-cloud", result.record["success_patterns"])
        self.assertEqual(result.record["score"], 94)
        prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("Generation goal JSON", prompt)
        self.assertIn("Trace JSON excerpt", prompt)

    def test_reasoning_max_tokens_takes_precedence_over_effort(self) -> None:
        self.assertEqual(
            make_reasoning_config("high", reasoning_max_tokens=128),
            {"max_tokens": 128, "exclude": True},
        )

    def test_pipeline_calls_planner_generator_validator_and_refiner(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        unsafe_svg = '<svg width="256" height="256"><script>alert(1)</script></svg>'
        client = FakeOpenRouterClient(
            [
                _goal_response(),
                _plan_response(item),
                _svg_response(unsafe_svg),
                _validation_response(
                    valid=False,
                    score=20,
                    issues=[{"code": "unsafe-tag", "severity": "error", "message": "Remove script."}],
                ),
                _failure_taxonomy_response(),
                _repair_route_response(),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
            ]
        )

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
            rewrite_prompt=False,
        )
        refinements = refine_artifacts(
            backend.plans,
            backend.artifacts,
            client=client,
            model="openai/gpt-oss-120b:free",
        )

        self.assertEqual(len(client.calls), 8)
        self.assertEqual(backend.traces[0].planner_backend, "openrouter")
        self.assertEqual(backend.traces[0].svg_backend, "openrouter")
        self.assertEqual(refinements[0].agent_statuses["validator"], "openrouter")
        self.assertEqual(refinements[0].agent_statuses["failure_taxonomy"], "openrouter")
        self.assertEqual(refinements[0].agent_statuses["repair_router"], "openrouter")
        self.assertEqual(refinements[0].agent_statuses["refiner"], "openrouter")
        self.assertEqual(refinements[0].failure_taxonomies[0].failure_types, ("syntax_safety", "renderability"))
        self.assertEqual(refinements[0].repair_routes[0].route, "safety_rebuild")
        self.assertEqual(refinements[0].rounds_used, 1)
        self.assertTrue(refinements[0].refined_report.is_valid)
        self.assertNotIn("<script", refinements[0].artifact.svg)

    def test_collaboration_agents_generate_critique_and_select_candidates(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        plan = _plan_response(item)
        plan_result = PlannerAgent(FakeOpenRouterClient([plan])).plan(item)
        client = FakeOpenRouterClient(
            [
                _svg_response(VALID_SVG),
                _svg_response(VALID_SVG.replace("Cloud Download", "Cloud Download Variant")),
                _critique_response(["candidate-1", "candidate-2"], scores=[72, 91]),
                _critique_response(["candidate-1", "candidate-2"], scores=[80, 88]),
                _selection_response("candidate-2"),
            ]
        )

        candidates = MultiCandidateGeneratorAgent(client).generate(plan_result.plan, candidate_count=2)
        tool_reports = [SvgCheckTool().check(candidate) for candidate in candidates.artifacts]
        semantic = SemanticCriticAgent(client).critique(plan_result.plan, list(candidates.artifacts))
        quality = SvgQualityCriticAgent(client).critique(
            plan_result.plan,
            list(candidates.artifacts),
            tool_reports,
        )
        selection = ConsensusSelectorAgent(client).select(
            plan_result.plan,
            list(candidates.artifacts),
            [semantic, quality],
            tool_reports,
        )

        self.assertEqual(len(client.calls), 5)
        self.assertEqual([candidate.stage for candidate in candidates.artifacts], ["candidate-1", "candidate-2"])
        self.assertEqual(semantic.perspective, "semantic")
        self.assertEqual(quality.perspective, "svg-quality")
        self.assertEqual(selection.winner_candidate_id, "candidate-2")
        self.assertIn("silhouette", selection.repair_brief)

    def test_optimizer_uses_llm_and_manual_feedback(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        plan_result = PlannerAgent(FakeOpenRouterClient([_plan_response(item)])).plan(item)
        selected = SvgArtifact(id=item.id, stage="selected", svg=VALID_SVG)
        semantic = _critique_response(["candidate-2"], scores=[91])
        quality = _critique_response(["candidate-2"], scores=[88])
        client = FakeOpenRouterClient(
            [
                semantic,
                quality,
                _selection_response("candidate-2"),
                _optimizer_response(),
            ]
        )
        candidates = [SvgArtifact(id=item.id, stage="candidate-2", svg=VALID_SVG)]
        tool_reports = [SvgCheckTool().check(candidates[0])]
        semantic_result = SemanticCriticAgent(client).critique(plan_result.plan, candidates)
        quality_result = SvgQualityCriticAgent(client).critique(plan_result.plan, candidates, tool_reports)
        selection = ConsensusSelectorAgent(client).select(
            plan_result.plan,
            candidates,
            [semantic_result, quality_result],
            tool_reports,
        )

        result = SvgOptimizerAgent(client).optimize(
            plan_result.plan,
            selected,
            [semantic_result, quality_result],
            tool_reports[0],
            selection,
            manual_feedback="make the arrow stronger",
            use_llm_feedback=True,
        )

        self.assertEqual(result.artifact.stage, "baseline")
        self.assertIn("manual_feedback", result.feedback_sources)
        optimizer_prompt = client.calls[-1]["messages"][1]["content"]
        self.assertIn("make the arrow stronger", optimizer_prompt)
        self.assertIn("LLM critic reports JSON", optimizer_prompt)
        self.assertIn("Consensus selector JSON", optimizer_prompt)

    def test_optimizer_can_disable_llm_feedback(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        plan_result = PlannerAgent(FakeOpenRouterClient([_plan_response(item)])).plan(item)
        selected = SvgArtifact(id=item.id, stage="selected", svg=VALID_SVG)
        selection = type(
            "Selection",
            (),
            {
                "winner_candidate_id": "candidate-1",
                "rationale": "Do not leak this rationale.",
                "risks": ("Do not leak this risk.",),
                "repair_brief": "Do not leak this repair brief.",
                "to_json": lambda self: {
                    "winner_candidate_id": self.winner_candidate_id,
                    "rationale": self.rationale,
                    "risks": list(self.risks),
                    "repair_brief": self.repair_brief,
                },
            },
        )()
        tool_report = SvgCheckTool().check(selected)
        client = FakeOpenRouterClient([_optimizer_response()])

        result = SvgOptimizerAgent(client).optimize(
            plan_result.plan,
            selected,
            [],
            tool_report,
            selection,
            manual_feedback="increase negative space",
            use_llm_feedback=False,
        )

        prompt = client.calls[0]["messages"][1]["content"]
        self.assertEqual(result.feedback_sources, ("svg_check_tool", "manual_feedback"))
        self.assertIn("increase negative space", prompt)
        self.assertIn("Deterministic SvgCheckTool report JSON", prompt)
        self.assertNotIn("LLM critic reports JSON", prompt)
        self.assertNotIn("Do not leak this rationale", prompt)
        self.assertNotIn("Do not leak this repair brief", prompt)

    def test_collaborative_backend_selects_candidate_and_records_trace(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient(_collaborative_success_responses(item)[:-1])

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            workflow="collaborative",
            candidate_count=3,
            client=client,
        )

        self.assertEqual(len(backend.artifacts), 1)
        self.assertEqual(len(backend.candidate_artifacts), 3)
        self.assertEqual(len(backend.selected_artifacts), 1)
        self.assertEqual(backend.traces[0].rewriter_backend, "openrouter")
        self.assertEqual(backend.traces[0].original_prompt, item.prompt)
        self.assertEqual(backend.traces[0].rewritten_prompt, item.prompt)
        self.assertEqual(backend.traces[0].workflow, "collaborative")
        self.assertEqual(backend.traces[0].selected_candidate_id, "candidate-2")
        self.assertEqual(backend.traces[0].svg_backend, "openrouter-collaborative")
        self.assertEqual(backend.traces[0].optimizer_backend, "openrouter")
        self.assertTrue(backend.traces[0].optimizer_applied)
        self.assertIn("semantic_critic", backend.traces[0].optimizer_feedback_sources)
        self.assertIn("optimizer", backend.traces[0].usage)
        self.assertIn("semantic", backend.traces[0].critic_scores)
        self.assertIn("semantic", backend.traces[0].critic_reports)
        self.assertEqual(
            backend.traces[0].critic_reports["semantic"]["candidate-2"]["recommendation"],
            "Keep this candidate concise.",
        )
        self.assertIn(item.id, backend.selection_briefs)

    def test_collaborative_optimizer_failure_does_not_use_selected_as_baseline(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        responses = _collaborative_success_responses(item)[:-2]
        responses.append(OpenRouterError("optimizer failed", debug_payload={"stage": "optimizer"}))
        client = FakeOpenRouterClient(responses)

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            workflow="collaborative",
            candidate_count=3,
            client=client,
        )

        self.assertEqual(backend.artifacts, [])
        self.assertEqual(backend.traces[0].optimizer_backend, "openrouter-error")
        self.assertFalse(backend.traces[0].optimizer_applied)
        self.assertIn("optimizer failed", backend.traces[0].errors[-1])

    def test_openrouter_failure_does_not_fall_back_to_local_svg(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient(
            [_goal_response(), OpenRouterError("rate limited", debug_payload={"body": "try later"})]
        )

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
            rewrite_prompt=False,
        )

        self.assertEqual(backend.artifacts, [])
        self.assertEqual(backend.traces[0].planner_backend, "openrouter-error")
        self.assertEqual(backend.traces[0].fallback_reason, None)
        self.assertIn("rate limited", backend.traces[0].errors[0])
        self.assertEqual(backend.raw_llm_events[1]["debug_payload"]["body"], "try later")

    def test_malformed_planner_json_logs_response_excerpt(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        malformed = 'The plan is {"category": "ui", "style": "line",}'
        client = FakeOpenRouterClient(
            [_goal_response(), OpenRouterResponse(content=malformed, model="openai/gpt-oss-120b:free")]
        )

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
            rewrite_prompt=False,
        )

        self.assertEqual(backend.artifacts, [])
        self.assertEqual(backend.raw_llm_events[1]["status"], "error")
        self.assertIn("content_excerpt", backend.raw_llm_events[1]["debug_payload"])
        self.assertIn("category", backend.raw_llm_events[1]["debug_payload"]["content_excerpt"])


class CliTests(unittest.TestCase):
    def test_cli_lists_prompt_cases_without_openrouter(self) -> None:
        stream = StringIO()

        with redirect_stdout(stream):
            exit_code = main(["--prompt", str(PROMPT_PATH), "--list-cases"])

        text = stream.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("rocket", text)
        self.assertIn("coffee", text)

    def test_cli_accepts_manual_text_and_writes_llm_outputs(self) -> None:
        prompt = "a minimal rocket launch icon with a dynamic flame"
        item = make_prompt_from_text(prompt)
        client = FakeOpenRouterClient(
            [
                _goal_response(),
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
                _memory_curator_response(),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch("svg_icon_agent.pipeline.create_openrouter_client", return_value=client):
                exit_code = main(
                    ["--text", prompt, "--out", str(output), "--workflow", "single", "--no-prompt-rewrite", "--quiet"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(list((output / "baseline").glob("*.svg"))), 1)
            self.assertEqual(len(list((output / "refined").glob("*.svg"))), 1)
            self.assertTrue((output / "gallery.html").exists())
            trace = json.loads((output / "llm_trace.json").read_text(encoding="utf-8"))
            self.assertEqual(trace[0]["planner_backend"], "openrouter")
            self.assertEqual(trace[0]["validator_backend"], "openrouter")

    def test_llm_trace_does_not_leak_api_key(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt)
        client = FakeOpenRouterClient(
            [
                _goal_response(),
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
                _memory_curator_response(),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch("svg_icon_agent.pipeline.create_openrouter_client", return_value=client):
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-test-key"}, clear=False):
                    exit_code = main(
                        ["--text", prompt, "--out", str(output), "--workflow", "single", "--no-prompt-rewrite", "--quiet"]
                    )

            self.assertEqual(exit_code, 0)

            trace_text = (output / "llm_trace.json").read_text(encoding="utf-8")
            raw_text = (output / "llm_raw_responses.jsonl").read_text(encoding="utf-8")
            self.assertEqual(exit_code, 0)
            self.assertNotIn("secret-test-key", trace_text)
            self.assertNotIn("secret-test-key", raw_text)
            self.assertNotIn("OPENROUTER_API_KEY", trace_text)


class WebAppTests(unittest.TestCase):
    def test_web_run_returns_artifacts_trace_and_raw_events(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        fake_client = FakeOpenRouterClient(
            [
                _goal_response(),
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
                _memory_curator_response(),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )
            client = app.test_client()

            response = client.post(
                "/api/runs",
                json={
                    "prompt": prompt,
                    "max_tokens": 4096,
                    "workflow": "single",
                    "rewrite_prompt": False,
                    "empty_response_retries": 4,
                    "reasoning_effort": "none",
                    "reasoning_max_tokens": 128,
                },
            )
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["max_tokens"], 4096)
            self.assertEqual(data["empty_response_retries"], 4)
            self.assertEqual(data["reasoning_effort"], "none")
            self.assertEqual(data["reasoning_max_tokens"], 128)
            self.assertIn("baseline_svg_text", data["artifacts"])
            self.assertIn("refined_png_url", data["artifacts"])
            self.assertEqual(data["trace"][0]["planner_backend"], "openrouter")
            self.assertEqual(data["trace"][0]["validator_backend"], "openrouter")
            self.assertIn(item.id, data["generation_goal"])
            self.assertIn(item.id, data["memory_context"])
            self.assertEqual(
                [event["stage"] for event in data["raw_events"]],
                ["goal-manager", "planner", "svg", "validator", "memory-curator"],
            )
            self.assertTrue(any(event["stage"] == "validator" for event in data["events"]))
            self.assertTrue(all(call["kwargs"]["max_tokens"] == 4096 for call in fake_client.calls))
            self.assertTrue(all(call["kwargs"]["reasoning"] == {"max_tokens": 128, "exclude": True} for call in fake_client.calls))

    def test_web_goal_and_memory_are_passed_to_llm_prompts(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        fake_client = FakeOpenRouterClient(
            [
                _goal_response(),
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
                _memory_curator_response(),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            MemoryRetrievalTool(root / "memory" / "memory_index.jsonl").append_record(
                MemoryRecord(
                    id="mem-cloud",
                    source_path="prior-run",
                    prompt="cloud download icon",
                    summary="Use a large central arrow and compact cloud silhouette.",
                    success_patterns=("large central arrow",),
                    user_feedback=("make the arrow stronger",),
                )
            )
            app = create_app(
                output_root=root,
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )

            data = app.test_client().post(
                "/api/runs",
                json={
                    "prompt": prompt,
                    "workflow": "single",
                    "rewrite_prompt": False,
                    "goal": "make it suitable for a mobile toolbar",
                    "memory_enabled": True,
                    "memory_top_k": 1,
                },
            ).get_json()

            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["memory_top_k"], 1)
            self.assertTrue(data["memory_enabled"])
            memory_records = data["memory_context"][item.id]["records"]
            self.assertEqual(memory_records[0]["id"], "mem-cloud")
            self.assertIn("mobile-toolbar", data["generation_goal"][item.id]["objective"])
            goal_prompt = fake_client.calls[0]["messages"][1]["content"]
            planner_prompt = fake_client.calls[1]["messages"][1]["content"]
            svg_prompt = fake_client.calls[2]["messages"][1]["content"]
            self.assertIn("make it suitable for a mobile toolbar", goal_prompt)
            self.assertIn("large central arrow", goal_prompt)
            self.assertIn("Generation goal JSON", planner_prompt)
            self.assertIn("Retrieved memory context", svg_prompt)

    def test_web_planner_failure_does_not_generate_local_fallback(self) -> None:
        fake_client = FakeOpenRouterClient(
            [_goal_response(), OpenRouterError("rate limited", debug_payload={"body": "try later"})]
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )
            client = app.test_client()

            response = client.post(
                "/api/runs",
                json={"prompt": "a minimal rocket launch icon", "workflow": "single", "rewrite_prompt": False},
            )
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "failed")
            self.assertEqual(data["artifacts"], {})
            self.assertEqual(data["trace"][0]["planner_backend"], "openrouter-error")
            self.assertEqual(data["raw_events"][1]["debug_payload"]["body"], "try later")

    def test_web_raw_response_does_not_leak_api_key(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        fake_client = FakeOpenRouterClient(
            [
                _goal_response(),
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
                _memory_curator_response(),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-test-key"}, clear=False):
                app = create_app(
                    output_root=Path(tmp),
                    client_factory=lambda model, timeout, retries: fake_client,
                    run_async=False,
                )
                response = app.test_client().post(
                    "/api/runs",
                    json={"prompt": prompt, "workflow": "single", "rewrite_prompt": False},
                )

            data = response.get_json()
            raw_text = json.dumps(data["raw_events"])
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("secret-test-key", raw_text)
            self.assertNotIn("OPENROUTER_API_KEY", raw_text)

    def test_web_collaborative_run_returns_candidates_and_selector_trace(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        fake_client = FakeOpenRouterClient(_collaborative_success_responses(item) + [_memory_curator_response()])
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )

            response = app.test_client().post(
                "/api/runs",
                json={"prompt": prompt, "workflow": "collaborative", "candidate_count": 3},
            )
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["workflow"], "collaborative")
            self.assertTrue(data["rewrite_prompt"])
            self.assertEqual(data["candidate_count"], 3)
            self.assertEqual(len(data["artifacts"]["candidates"]), 3)
            self.assertIn("selected_svg_text", data["artifacts"])
            self.assertIn("baseline_svg_text", data["artifacts"])
            self.assertEqual(data["trace"][0]["rewriter_backend"], "openrouter")
            self.assertEqual(data["trace"][0]["original_prompt"], prompt)
            self.assertEqual(data["trace"][0]["rewritten_prompt"], prompt)
            self.assertEqual(data["trace"][0]["selected_candidate_id"], "candidate-2")
            self.assertEqual(data["trace"][0]["svg_backend"], "openrouter-collaborative")
            self.assertEqual(data["trace"][0]["optimizer_backend"], "openrouter")
            self.assertTrue(data["trace"][0]["optimizer_applied"])
            self.assertIn("svg_check_tool", data["trace"][0]["optimizer_feedback_sources"])
            self.assertEqual(data["trace"][0]["critic_reports"]["semantic"]["candidate-2"]["score"], 91)
            self.assertEqual(
                data["trace"][0]["critic_reports"]["svg-quality"]["candidate-2"]["recommendation"],
                "Keep this candidate concise.",
            )

    def test_web_accepts_optimizer_feedback_options(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        fake_client = FakeOpenRouterClient(_collaborative_success_responses(item) + [_memory_curator_response()])
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )

            response = app.test_client().post(
                "/api/runs",
                json={
                    "prompt": prompt,
                    "workflow": "collaborative",
                    "candidate_count": 3,
                    "optimizer_feedback": "make the cloud more compact",
                    "use_llm_optimizer_feedback": False,
                },
            )
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["optimizer_feedback"], "make the cloud more compact")
            self.assertFalse(data["use_llm_optimizer_feedback"])
            self.assertEqual(data["trace"][0]["manual_optimizer_feedback"], "make the cloud more compact")
            self.assertFalse(data["trace"][0]["use_llm_optimizer_feedback"])
            self.assertEqual(data["trace"][0]["optimizer_feedback_sources"], ["svg_check_tool", "manual_feedback"])

    def test_web_can_apply_manual_feedback_after_completed_run(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        post_svg = VALID_SVG.replace("Cloud Download", "Post Optimized Cloud Download")
        fake_client = FakeOpenRouterClient(
            _collaborative_success_responses(item)
            + [
                _memory_curator_response(),
                _optimizer_response(post_svg),
                _validation_response(valid=True, score=98, issues=[]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )
            client = app.test_client()

            initial = client.post(
                "/api/runs",
                json={"prompt": prompt, "workflow": "collaborative", "candidate_count": 3},
            ).get_json()
            initial_png_url = initial["artifacts"]["refined_png_url"]
            time.sleep(0.001)
            response = client.post(
                f"/api/runs/{initial['id']}/optimize",
                json={
                    "optimizer_feedback": "make the arrow larger and simplify the cloud",
                    "use_llm_optimizer_feedback": False,
                },
            )
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "completed")
            self.assertIn("Post Optimized Cloud Download", data["artifacts"]["baseline_svg_text"])
            self.assertIn("Post Optimized Cloud Download", data["artifacts"]["refined_svg_text"])
            self.assertIn("v=", data["artifacts"]["refined_png_url"])
            self.assertNotEqual(data["artifacts"]["refined_png_url"], initial_png_url)
            self.assertEqual(data["trace"][0]["post_run_optimizer_backend"], "openrouter")
            self.assertTrue(data["trace"][0]["post_run_optimizer_applied"])
            self.assertEqual(data["trace"][0]["post_run_optimizer_feedback"], "make the arrow larger and simplify the cloud")
            self.assertFalse(data["trace"][0]["post_run_use_llm_feedback"])
            self.assertEqual(data["trace"][0]["post_run_optimizer_feedback_sources"], ["svg_check_tool", "manual_feedback"])
            self.assertTrue(any(event["stage"] == "post-run-optimizer" for event in data["raw_events"]))

    def test_web_returns_rewritten_prompt_before_run_finishes(self) -> None:
        prompt = "rocket"
        rewritten = (
            "a minimal rocket launch icon with a centered upward silhouette, clear fins, compact smoke puffs, "
            "and a bold flame shape readable at small size"
        )
        fake_client = BlockingAfterRewriteClient(rewritten)
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=True,
            )
            client = app.test_client()

            response = client.post("/api/runs", json={"prompt": prompt, "workflow": "single"})
            data = response.get_json()
            run_id = data["id"]
            self.assertTrue(fake_client.rewrite_done.wait(timeout=2.0))

            live = client.get(f"/api/runs/{run_id}").get_json()

            self.assertEqual(live["prompt_rewrite"]["original_prompt"], prompt)
            self.assertEqual(live["prompt_rewrite"]["rewritten_prompt"], rewritten)
            fake_client.allow_continue.set()
            for _ in range(20):
                final = client.get(f"/api/runs/{run_id}").get_json()
                if final["status"] == "failed":
                    break
                time.sleep(0.05)

    def test_web_outputs_route_serves_png_from_relative_output_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            root = Path(tmp) / "outputs" / "web"
            target = root / "run-id" / "png" / "refined" / "icon.png"
            target.parent.mkdir(parents=True)
            render_svg_to_png(VALID_SVG, target)
            app = create_app(output_root=root.relative_to(Path.cwd()), run_async=False)

            response = app.test_client().get("/outputs/run-id/png/refined/icon.png")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content_type, "image/png")
            self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")
            response.close()


if __name__ == "__main__":
    unittest.main()
