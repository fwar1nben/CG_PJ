"""Pipeline checks for the SVG Icon Agent."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from pathlib import Path

from svg_icon_agent.backends import generate_with_backend
from svg_icon_agent.cli import main
from svg_icon_agent.exporter import render_svg_to_png
from svg_icon_agent.generator import SvgGeneratorAgent
from svg_icon_agent.llm_agents import OpenRouterPlannerAgent
from svg_icon_agent.openrouter_client import OpenRouterError, OpenRouterResponse
from svg_icon_agent.planner import plan_prompts
from svg_icon_agent.prompts import load_prompts
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.validator import validate_artifacts


PROMPT_PATH = Path("prompts/examples.json")


class FakeOpenRouterClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, **kwargs):
        if not self.responses:
            raise AssertionError("FakeOpenRouterClient has no remaining responses.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class PromptTests(unittest.TestCase):
    def test_examples_have_expected_coverage(self) -> None:
        prompts = load_prompts(PROMPT_PATH)

        self.assertEqual(len(prompts), 12)
        self.assertEqual({item.category for item in prompts}, {"ui", "object", "scene"})
        self.assertEqual(len({item.id for item in prompts}), 12)


class PipelineTests(unittest.TestCase):
    def test_refinement_repairs_all_baseline_icons(self) -> None:
        prompts = load_prompts(PROMPT_PATH)
        plans = plan_prompts(prompts)
        generator = SvgGeneratorAgent()
        baseline = [generator.generate(plan) for plan in plans]

        baseline_reports = validate_artifacts(baseline)
        refinements = refine_artifacts(plans, baseline, max_rounds=3)
        refined_reports = validate_artifacts([result.artifact for result in refinements])

        self.assertEqual(sum(report.is_valid for report in baseline_reports), 0)
        self.assertEqual(sum(report.is_valid for report in refined_reports), 12)
        self.assertTrue(all(result.rounds_used <= 3 for result in refinements))
        self.assertTrue(all(report.score == 100 for report in refined_reports))

    def test_cli_exports_svg_png_gallery_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)

            exit_code = main(["--prompt", str(PROMPT_PATH), "--out", str(output), "--backend", "rule", "--quiet"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(list((output / "baseline").glob("*.svg"))), 12)
            self.assertEqual(len(list((output / "refined").glob("*.svg"))), 12)
            self.assertEqual(len(list((output / "png" / "baseline").glob("*.png"))), 12)
            self.assertEqual(len(list((output / "png" / "refined").glob("*.png"))), 12)
            self.assertTrue((output / "gallery.html").exists())
            metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["total"], 12)
            self.assertEqual(metrics["refined_valid"], 12)
            self.assertGreater(metrics["average_score_delta"], 0)

    def test_cli_prints_realtime_progress_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            stream = StringIO()

            with redirect_stdout(stream):
                exit_code = main(["--prompt", str(PROMPT_PATH), "--out", str(output), "--backend", "rule"])

            text = stream.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Loading prompts", text)
            self.assertIn("Pipeline complete", text)

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


class OpenRouterBackendTests(unittest.TestCase):
    def test_openrouter_planner_json_converts_to_icon_plan(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient(
            [
                OpenRouterResponse(
                    content=json.dumps(
                        {
                            "category": "ui",
                            "style": "line",
                            "palette": ["#2563eb", "#dbeafe", "#111827"],
                            "motifs": ["cloud", "download-arrow"],
                            "layout": "centered badge",
                            "constraints": ["safe-svg-primitives-only"],
                        }
                    ),
                    model="openai/gpt-oss-120b:free",
                    usage={"prompt_tokens": 10, "completion_tokens": 20},
                )
            ]
        )

        result = OpenRouterPlannerAgent(client).plan(item)

        self.assertEqual(result.plan.id, item.id)
        self.assertEqual(result.plan.category, "ui")
        self.assertIn("cloud", result.plan.motifs)
        self.assertIn("square-256-canvas", result.plan.constraints)
        self.assertEqual(result.response.usage["completion_tokens"], 20)

    def test_openrouter_svg_draft_can_enter_refinement_pipeline(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>Cloud Download</title>
  <desc>Cloud download icon</desc>
  <rect x="20" y="20" width="216" height="216" rx="40" fill="#dbeafe"/>
  <circle cx="95" cy="126" r="36" fill="white" stroke="#111827" stroke-width="8"/>
  <circle cx="134" cy="112" r="44" fill="white" stroke="#111827" stroke-width="8"/>
  <line x1="128" y1="91" x2="128" y2="172" stroke="#2563eb" stroke-width="12"/>
  <polyline points="101,145 128,174 155,145" fill="none" stroke="#2563eb" stroke-width="12"/>
</svg>"""
        client = FakeOpenRouterClient(
            [
                OpenRouterResponse(
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
                    usage={"prompt_tokens": 1},
                    raw={"choices": [{"message": {"content": "plan-json"}}]},
                ),
                OpenRouterResponse(
                    content=svg,
                    model="openai/gpt-oss-120b:free",
                    usage={"completion_tokens": 1},
                    raw={"choices": [{"message": {"content": svg}}]},
                ),
            ]
        )

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
        )
        refinements = refine_artifacts(backend.plans, backend.artifacts)
        refined_reports = validate_artifacts([result.artifact for result in refinements])

        self.assertEqual(backend.traces[0].planner_backend, "openrouter")
        self.assertEqual(backend.traces[0].svg_backend, "openrouter")
        self.assertEqual([event["stage"] for event in backend.raw_llm_events], ["planner", "svg"])
        self.assertEqual(backend.raw_llm_events[1]["response"]["choices"][0]["message"]["content"], svg)
        self.assertTrue(refined_reports[0].is_valid)

    def test_openrouter_failures_fall_back_to_rule_backend(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient([OpenRouterError("rate limited", debug_payload={"body": "try later"})])

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
        )

        self.assertEqual(backend.traces[0].planner_backend, "rule")
        self.assertEqual(backend.traces[0].svg_backend, "rule")
        self.assertIn("llm-plan-failed", backend.traces[0].fallback_reason)
        self.assertEqual(backend.raw_llm_events[0]["debug_payload"]["body"], "try later")
        self.assertIn("data-prompt", backend.artifacts[0].svg)

    def test_invalid_llm_svg_falls_back_to_rule_svg(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient(
            [
                OpenRouterResponse(
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
                ),
                OpenRouterResponse(
                    content='<svg width="256" height="256"><script>alert(1)</script></svg>',
                    model="openai/gpt-oss-120b:free",
                ),
            ]
        )

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
        )

        self.assertEqual(backend.traces[0].planner_backend, "openrouter")
        self.assertEqual(backend.traces[0].svg_backend, "rule")
        self.assertIn("llm-svg-failed", backend.traces[0].fallback_reason)

    def test_llm_trace_does_not_leak_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-test-key"}, clear=False):
                exit_code = main(["--prompt", str(PROMPT_PATH), "--out", str(output), "--backend", "rule", "--quiet"])

            trace_text = (output / "llm_trace.json").read_text(encoding="utf-8")
            self.assertEqual(exit_code, 0)
            self.assertNotIn("secret-test-key", trace_text)
            self.assertNotIn("OPENROUTER_API_KEY", trace_text)


if __name__ == "__main__":
    unittest.main()
