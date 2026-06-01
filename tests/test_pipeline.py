"""Pipeline checks for the SVG Icon Agent."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from svg_icon_agent.cli import main
from svg_icon_agent.generator import SvgGeneratorAgent
from svg_icon_agent.planner import plan_prompts
from svg_icon_agent.prompts import load_prompts
from svg_icon_agent.refiner import refine_artifacts
from svg_icon_agent.validator import validate_artifacts


PROMPT_PATH = Path("prompts/examples.json")


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

            exit_code = main(["--prompt", str(PROMPT_PATH), "--out", str(output)])

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


if __name__ == "__main__":
    unittest.main()

