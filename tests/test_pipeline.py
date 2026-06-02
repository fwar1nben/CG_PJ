"""Pipeline checks for the SVG Icon Agent."""

from __future__ import annotations

import inspect
import json
import os
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
    OpenRouterPlannerAgent,
    OpenRouterRefinerAgent,
    OpenRouterSvgGeneratorAgent,
    OpenRouterValidatorAgent,
)
from svg_icon_agent.openrouter_client import OpenRouterClient, OpenRouterError, OpenRouterResponse
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
            OpenRouterPlannerAgent,
            OpenRouterSvgGeneratorAgent,
            OpenRouterValidatorAgent,
            OpenRouterRefinerAgent,
        ):
            annotations = inspect.get_annotations(cls.__init__, eval_str=True)
            self.assertEqual(annotations["client"], OpenRouterClient)

    def test_hardcoded_rule_generator_module_was_removed(self) -> None:
        self.assertFalse(Path("svg_icon_agent/generator.py").exists())


class OpenRouterPipelineTests(unittest.TestCase):
    def test_openrouter_planner_json_converts_to_icon_plan(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient([_plan_response(item)])

        result = OpenRouterPlannerAgent(client, max_tokens=4096).plan(item)

        self.assertEqual(result.plan.id, item.id)
        self.assertEqual(result.plan.category, "ui")
        self.assertIn("cloud", result.plan.motifs)
        self.assertIn("square-256-canvas", result.plan.constraints)
        self.assertEqual(result.response.usage["completion_tokens"], 20)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["kwargs"]["max_tokens"], 4096)

    def test_pipeline_calls_planner_generator_validator_and_refiner(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        unsafe_svg = '<svg width="256" height="256"><script>alert(1)</script></svg>'
        client = FakeOpenRouterClient(
            [
                _plan_response(item),
                _svg_response(unsafe_svg),
                _validation_response(
                    valid=False,
                    score=20,
                    issues=[{"code": "unsafe-tag", "severity": "error", "message": "Remove script."}],
                ),
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
        )
        refinements = refine_artifacts(
            backend.plans,
            backend.artifacts,
            client=client,
            model="openai/gpt-oss-120b:free",
        )

        self.assertEqual(len(client.calls), 5)
        self.assertEqual(backend.traces[0].planner_backend, "openrouter")
        self.assertEqual(backend.traces[0].svg_backend, "openrouter")
        self.assertEqual(refinements[0].agent_statuses["validator"], "openrouter")
        self.assertEqual(refinements[0].agent_statuses["refiner"], "openrouter")
        self.assertEqual(refinements[0].rounds_used, 1)
        self.assertTrue(refinements[0].refined_report.is_valid)
        self.assertNotIn("<script", refinements[0].artifact.svg)

    def test_openrouter_failure_does_not_fall_back_to_local_svg(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        client = FakeOpenRouterClient([OpenRouterError("rate limited", debug_payload={"body": "try later"})])

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
        )

        self.assertEqual(backend.artifacts, [])
        self.assertEqual(backend.traces[0].planner_backend, "openrouter-error")
        self.assertEqual(backend.traces[0].fallback_reason, None)
        self.assertIn("rate limited", backend.traces[0].errors[0])
        self.assertEqual(backend.raw_llm_events[0]["debug_payload"]["body"], "try later")

    def test_malformed_planner_json_logs_response_excerpt(self) -> None:
        item = load_prompts(PROMPT_PATH)[0]
        malformed = 'The plan is {"category": "ui", "style": "line",}'
        client = FakeOpenRouterClient([OpenRouterResponse(content=malformed, model="openai/gpt-oss-120b:free")])

        backend = generate_with_backend(
            [item],
            backend="openrouter",
            model="openai/gpt-oss-120b:free",
            llm_stage="plan-svg",
            client=client,
        )

        self.assertEqual(backend.artifacts, [])
        self.assertEqual(backend.raw_llm_events[0]["status"], "error")
        self.assertIn("content_excerpt", backend.raw_llm_events[0]["debug_payload"])
        self.assertIn("category", backend.raw_llm_events[0]["debug_payload"]["content_excerpt"])


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
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch("svg_icon_agent.pipeline.create_openrouter_client", return_value=client):
                exit_code = main(["--text", prompt, "--out", str(output), "--quiet"])

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
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch("svg_icon_agent.pipeline.create_openrouter_client", return_value=client):
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-test-key"}, clear=False):
                    exit_code = main(["--text", prompt, "--out", str(output), "--quiet"])

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
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )
            client = app.test_client()

            response = client.post("/api/runs", json={"prompt": prompt, "max_tokens": 4096})
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["max_tokens"], 4096)
            self.assertIn("baseline_svg_text", data["artifacts"])
            self.assertIn("refined_png_url", data["artifacts"])
            self.assertEqual(data["trace"][0]["planner_backend"], "openrouter")
            self.assertEqual(data["trace"][0]["validator_backend"], "openrouter")
            self.assertEqual([event["stage"] for event in data["raw_events"]], ["planner", "svg", "validator"])
            self.assertTrue(any(event["stage"] == "validator" for event in data["events"]))
            self.assertTrue(all(call["kwargs"]["max_tokens"] == 4096 for call in fake_client.calls))

    def test_web_planner_failure_does_not_generate_local_fallback(self) -> None:
        fake_client = FakeOpenRouterClient([OpenRouterError("rate limited", debug_payload={"body": "try later"})])
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_root=Path(tmp),
                client_factory=lambda model, timeout, retries: fake_client,
                run_async=False,
            )
            client = app.test_client()

            response = client.post("/api/runs", json={"prompt": "a minimal rocket launch icon"})
            data = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "failed")
            self.assertEqual(data["artifacts"], {})
            self.assertEqual(data["trace"][0]["planner_backend"], "openrouter-error")
            self.assertEqual(data["raw_events"][0]["debug_payload"]["body"], "try later")

    def test_web_raw_response_does_not_leak_api_key(self) -> None:
        prompt = "a minimal cloud download icon with a clear arrow"
        item = make_prompt_from_text(prompt, source="web")
        fake_client = FakeOpenRouterClient(
            [
                _plan_response(item),
                _svg_response(VALID_SVG),
                _validation_response(valid=True, score=100, issues=[]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "secret-test-key"}, clear=False):
                app = create_app(
                    output_root=Path(tmp),
                    client_factory=lambda model, timeout, retries: fake_client,
                    run_async=False,
                )
                response = app.test_client().post("/api/runs", json={"prompt": prompt})

            data = response.get_json()
            raw_text = json.dumps(data["raw_events"])
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("secret-test-key", raw_text)
            self.assertNotIn("OPENROUTER_API_KEY", raw_text)


if __name__ == "__main__":
    unittest.main()
