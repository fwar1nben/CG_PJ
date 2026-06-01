"""Backend selection and fallback orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from svg_icon_agent.generator import SvgGeneratorAgent
from svg_icon_agent.llm_agents import OpenRouterPlannerAgent, OpenRouterSvgGeneratorAgent
from svg_icon_agent.models import IconPlan, SvgArtifact, ValidationReport
from svg_icon_agent.openrouter_client import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterClient,
    OpenRouterConfig,
    OpenRouterError,
    has_openrouter_key,
)
from svg_icon_agent.planner import PlannerAgent
from svg_icon_agent.prompts import PromptItem
from svg_icon_agent.validator import ValidatorAgent


@dataclass
class BackendTrace:
    id: str
    requested_backend: str
    model: str
    llm_stage: str
    planner_backend: str = "rule"
    svg_backend: str = "rule"
    fallback_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def to_json(
        self,
        baseline_report: ValidationReport | None = None,
        refined_report: ValidationReport | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "requested_backend": self.requested_backend,
            "model": self.model,
            "llm_stage": self.llm_stage,
            "planner_backend": self.planner_backend,
            "svg_backend": self.svg_backend,
            "fallback_reason": self.fallback_reason,
            "usage": self.usage,
        }
        if baseline_report is not None:
            data["baseline_score"] = baseline_report.score
            data["baseline_valid"] = baseline_report.is_valid
        if refined_report is not None:
            data["refined_score"] = refined_report.score
            data["refined_valid"] = refined_report.is_valid
        if baseline_report is not None and refined_report is not None:
            data["score_delta"] = refined_report.score - baseline_report.score
        return data


@dataclass(frozen=True)
class BackendResult:
    plans: list[IconPlan]
    artifacts: list[SvgArtifact]
    traces: list[BackendTrace]
    active_backend: str


def generate_with_backend(
    prompts: list[PromptItem],
    *,
    backend: str,
    model: str | None = None,
    llm_stage: str = "plan-svg",
    client: OpenRouterClient | None = None,
) -> BackendResult:
    model_name = model or DEFAULT_OPENROUTER_MODEL
    if backend == "rule":
        return _rule_backend(prompts, backend, model_name, llm_stage)
    if backend == "auto" and client is None and not has_openrouter_key():
        return _rule_backend(prompts, backend, model_name, llm_stage, "auto-no-api-key")

    try:
        openrouter_client = client or OpenRouterClient(OpenRouterConfig.from_env(model=model_name))
    except OpenRouterError as exc:
        return _rule_backend(prompts, backend, model_name, llm_stage, str(exc))

    return _openrouter_backend(
        prompts,
        requested_backend=backend,
        model=model_name,
        llm_stage=llm_stage,
        client=openrouter_client,
    )


def _rule_backend(
    prompts: list[PromptItem],
    requested_backend: str,
    model: str,
    llm_stage: str,
    fallback_reason: str | None = None,
) -> BackendResult:
    planner = PlannerAgent()
    generator = SvgGeneratorAgent()
    plans = [planner.plan(item) for item in prompts]
    artifacts = [generator.generate(plan) for plan in plans]
    traces = [
        BackendTrace(
            id=item.id,
            requested_backend=requested_backend,
            model=model,
            llm_stage=llm_stage,
            fallback_reason=fallback_reason,
        )
        for item in prompts
    ]
    return BackendResult(plans=plans, artifacts=artifacts, traces=traces, active_backend="rule")


def _openrouter_backend(
    prompts: list[PromptItem],
    *,
    requested_backend: str,
    model: str,
    llm_stage: str,
    client: OpenRouterClient,
) -> BackendResult:
    rule_planner = PlannerAgent()
    rule_generator = SvgGeneratorAgent()
    validator = ValidatorAgent()
    llm_planner = OpenRouterPlannerAgent(client)
    llm_generator = OpenRouterSvgGeneratorAgent(client)

    plans: list[IconPlan] = []
    artifacts: list[SvgArtifact] = []
    traces: list[BackendTrace] = []

    for item in prompts:
        trace = BackendTrace(
            id=item.id,
            requested_backend=requested_backend,
            model=model,
            llm_stage=llm_stage,
        )
        rule_plan = rule_planner.plan(item)
        plan = rule_plan
        artifact: SvgArtifact | None = None

        try:
            plan_result = llm_planner.plan(item)
        except OpenRouterError as exc:
            trace.fallback_reason = f"llm-plan-failed: {exc}"
            artifact = rule_generator.generate(rule_plan)
        else:
            plan = plan_result.plan
            trace.planner_backend = "openrouter"
            trace.usage["planner"] = plan_result.response.usage

        if artifact is None and llm_stage == "plan-svg":
            try:
                svg_result = llm_generator.generate(plan)
                draft_report = validator.validate(svg_result.artifact)
                if not draft_report.is_valid:
                    issue_codes = ",".join(issue.code for issue in draft_report.issues if issue.severity == "error")
                    raise OpenRouterError(f"llm-svg-validation-error: {issue_codes}")
            except OpenRouterError as exc:
                trace.fallback_reason = f"llm-svg-failed: {exc}"
                artifact = rule_generator.generate(plan)
            else:
                artifact = svg_result.artifact
                trace.svg_backend = "openrouter"
                trace.usage["svg"] = svg_result.response.usage
        elif artifact is None:
            artifact = rule_generator.generate(plan)

        plans.append(plan)
        artifacts.append(artifact)
        traces.append(trace)

    return BackendResult(plans=plans, artifacts=artifacts, traces=traces, active_backend="openrouter")

