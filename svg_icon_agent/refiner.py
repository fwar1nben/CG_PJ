"""LLM-backed refinement loop for SVG artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from svg_icon_agent.llm_agents import FailureTaxonomyAgent, RefinerAgent, RepairRouterAgent, ValidatorAgent
from svg_icon_agent.models import FailureTaxonomy, IconPlan, RepairRoute, SvgArtifact, ValidationIssue, ValidationReport
from svg_icon_agent.openrouter_client import DEFAULT_OPENROUTER_MODEL, OpenRouterClient, OpenRouterError
from svg_icon_agent.progress import ProgressLogger
from svg_icon_agent.svg_check_tool import SvgCheckTool


@dataclass(frozen=True)
class RefinementResult:
    id: str
    artifact: SvgArtifact
    reports: tuple[ValidationReport, ...]
    rounds_used: int
    failure_taxonomies: tuple[FailureTaxonomy, ...] = field(default_factory=tuple)
    repair_routes: tuple[RepairRoute, ...] = field(default_factory=tuple)
    raw_llm_events: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    usage: dict[str, Any] = field(default_factory=dict)
    agent_statuses: dict[str, str] = field(default_factory=dict)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def baseline_report(self) -> ValidationReport:
        return self.reports[0] if self.reports else _empty_report(self.id, "baseline")

    @property
    def refined_report(self) -> ValidationReport:
        if not self.reports:
            return _empty_report(self.id, "refined")
        report = self.reports[-1]
        return ValidationReport(
            id=report.id,
            stage="refined",
            score=report.score,
            issues=report.issues,
        )

    def to_json(self) -> dict[str, object]:
        first_score = self.baseline_report.score
        final_score = self.refined_report.score
        return {
            "id": self.id,
            "rounds_used": self.rounds_used,
            "initial_score": first_score,
            "final_score": final_score,
            "score_delta": final_score - first_score,
            "accepted": self.refined_report.is_valid,
            "reports": [report.to_json() for report in self.reports],
            "failure_taxonomies": [taxonomy.to_json() for taxonomy in self.failure_taxonomies],
            "repair_routes": [route.to_json() for route in self.repair_routes],
            "agent_statuses": self.agent_statuses,
            "errors": list(self.errors),
        }


def refine_artifacts(
    plans: list[IconPlan],
    artifacts: list[SvgArtifact],
    *,
    client: OpenRouterClient,
    max_rounds: int = 3,
    model: str = DEFAULT_OPENROUTER_MODEL,
    max_tokens: int | None = None,
    reasoning: dict[str, Any] | None = None,
    collaboration_briefs: dict[str, str] | None = None,
    progress: ProgressLogger | None = None,
) -> list[RefinementResult]:
    by_id = {plan.id: plan for plan in plans}
    missing = sorted(artifact.id for artifact in artifacts if artifact.id not in by_id)
    if missing:
        raise ValueError(f"Missing LLM plans for artifacts: {', '.join(missing)}")

    logger = progress or ProgressLogger(verbose=False)
    checker = SvgCheckTool()
    llm_validator = ValidatorAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    taxonomy_agent = FailureTaxonomyAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    repair_router = RepairRouterAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    llm_refiner = RefinerAgent(client, max_tokens=max_tokens, reasoning=reasoning)
    results: list[RefinementResult] = []

    total = len(artifacts)
    for index, artifact in enumerate(artifacts, start=1):
        plan = by_id[artifact.id]
        logger.log(f"[{index}/{total}] {artifact.id}: starting LLM validation/refinement loop.")
        results.append(
            _refine_one(
                plan,
                artifact,
                checker=checker,
                llm_validator=llm_validator,
                taxonomy_agent=taxonomy_agent,
                repair_router=repair_router,
                llm_refiner=llm_refiner,
                max_rounds=max_rounds,
                model=model,
                collaboration_brief=(collaboration_briefs or {}).get(artifact.id),
                progress=logger,
                index=index,
                total=total,
            )
        )
    return results


def _refine_one(
    plan: IconPlan,
    artifact: SvgArtifact,
    *,
    checker: SvgCheckTool,
    llm_validator: ValidatorAgent,
    taxonomy_agent: FailureTaxonomyAgent,
    repair_router: RepairRouterAgent,
    llm_refiner: RefinerAgent,
    max_rounds: int,
    model: str,
    collaboration_brief: str | None,
    progress: ProgressLogger,
    index: int,
    total: int,
) -> RefinementResult:
    current = artifact
    reports: list[ValidationReport] = []
    failure_taxonomies: list[FailureTaxonomy] = []
    repair_routes: list[RepairRoute] = []
    raw_events: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    errors: list[str] = []
    validator_status = "not-run"
    taxonomy_status = "not-run"
    router_status = "not-run"
    refiner_status = "not-run"
    rounds_used = 0

    for round_index in range(max_rounds + 1):
        tool_report = checker.check(current)
        progress.log(f"[{index}/{total}] {artifact.id}: requesting LLM validator round {round_index}.")
        try:
            validation_result = llm_validator.validate(plan, current, tool_report, round_index=round_index)
        except OpenRouterError as exc:
            validator_status = "openrouter-error"
            errors.append(f"validator round {round_index}: {exc}")
            raw_events.append(_raw_event(artifact.id, "validator", "error", model, error=exc, round_index=round_index))
            reports.append(_llm_failure_report(current, tool_report, exc))
            progress.log(f"[{index}/{total}] {artifact.id}: LLM validator failed; stopping refinement.")
            break

        validator_status = "openrouter"
        report = validation_result.report
        reports.append(report)
        usage[f"validator_round_{round_index}"] = validation_result.response.usage
        raw_events.append(
            _raw_event(
                artifact.id,
                "validator",
                "success",
                model,
                response=validation_result.response.raw,
                round_index=round_index,
            )
        )
        progress.log(f"[{index}/{total}] {artifact.id}: LLM validator score={report.score}, valid={report.is_valid}.")

        blocking_issues = [issue for issue in report.issues if issue.severity in {"error", "warning"}]
        if not blocking_issues:
            break
        if rounds_used >= max_rounds:
            break

        progress.log(f"[{index}/{total}] {artifact.id}: requesting failure taxonomy round {round_index + 1}.")
        try:
            taxonomy_result = taxonomy_agent.classify(
                plan,
                current,
                report,
                tool_report,
                round_index=round_index + 1,
            )
        except OpenRouterError as exc:
            taxonomy_status = "openrouter-error"
            errors.append(f"failure taxonomy round {round_index + 1}: {exc}")
            raw_events.append(
                _raw_event(artifact.id, "failure-taxonomy", "error", model, error=exc, round_index=round_index + 1)
            )
            progress.log(f"[{index}/{total}] {artifact.id}: failure taxonomy failed; stopping refinement.")
            break

        taxonomy_status = "openrouter"
        taxonomy = taxonomy_result.taxonomy
        failure_taxonomies.append(taxonomy)
        usage[f"failure_taxonomy_round_{round_index + 1}"] = taxonomy_result.response.usage
        raw_events.append(
            _raw_event(
                artifact.id,
                "failure-taxonomy",
                "success",
                model,
                response=taxonomy_result.response.raw,
                round_index=round_index + 1,
            )
        )

        progress.log(f"[{index}/{total}] {artifact.id}: requesting repair router round {round_index + 1}.")
        try:
            route_result = repair_router.route(
                plan,
                current,
                report,
                tool_report,
                taxonomy,
                round_index=round_index + 1,
                collaboration_brief=collaboration_brief,
            )
        except OpenRouterError as exc:
            router_status = "openrouter-error"
            errors.append(f"repair router round {round_index + 1}: {exc}")
            raw_events.append(
                _raw_event(artifact.id, "repair-router", "error", model, error=exc, round_index=round_index + 1)
            )
            progress.log(f"[{index}/{total}] {artifact.id}: repair router failed; stopping refinement.")
            break

        router_status = "openrouter"
        repair_route = route_result.route
        repair_routes.append(repair_route)
        usage[f"repair_router_round_{round_index + 1}"] = route_result.response.usage
        raw_events.append(
            _raw_event(
                artifact.id,
                "repair-router",
                "success",
                model,
                response=route_result.response.raw,
                round_index=round_index + 1,
            )
        )

        progress.log(f"[{index}/{total}] {artifact.id}: requesting LLM refiner round {round_index + 1}.")
        try:
            refinement_result = llm_refiner.refine(
                plan,
                current,
                report,
                tool_report,
                round_index=round_index + 1,
                collaboration_brief=collaboration_brief,
                repair_route=repair_route,
            )
        except OpenRouterError as exc:
            refiner_status = "openrouter-error"
            errors.append(f"refiner round {round_index + 1}: {exc}")
            raw_events.append(_raw_event(artifact.id, "refiner", "error", model, error=exc, round_index=round_index + 1))
            progress.log(f"[{index}/{total}] {artifact.id}: LLM refiner failed; keeping current SVG.")
            break

        refiner_status = "openrouter"
        usage[f"refiner_round_{round_index + 1}"] = refinement_result.response.usage
        raw_events.append(
            _raw_event(
                artifact.id,
                "refiner",
                "success",
                model,
                response=refinement_result.response.raw,
                round_index=round_index + 1,
            )
        )
        current = refinement_result.artifact
        rounds_used += 1

    if current.stage != "refined":
        current = SvgArtifact(id=current.id, stage="refined", svg=current.svg)

    return RefinementResult(
        id=artifact.id,
        artifact=current,
        reports=tuple(reports),
        rounds_used=rounds_used,
        failure_taxonomies=tuple(failure_taxonomies),
        repair_routes=tuple(repair_routes),
        raw_llm_events=tuple(raw_events),
        usage=usage,
        agent_statuses={
            "validator": validator_status,
            "failure_taxonomy": taxonomy_status,
            "repair_router": router_status,
            "refiner": refiner_status,
        },
        errors=tuple(errors),
    )


def _llm_failure_report(
    artifact: SvgArtifact,
    tool_report: ValidationReport,
    error: OpenRouterError,
) -> ValidationReport:
    issues = list(tool_report.issues)
    issues.append(
        ValidationIssue(
            code="llm-validator-failed",
            severity="error",
            message=f"OpenRouter validator failed: {error}",
        )
    )
    return ValidationReport(
        id=artifact.id,
        stage=artifact.stage,
        score=0,
        issues=tuple(issues),
    )


def _empty_report(prompt_id: str, stage: str) -> ValidationReport:
    return ValidationReport(
        id=prompt_id,
        stage=stage,
        score=0,
        issues=(
            ValidationIssue(
                code="missing-report",
                severity="error",
                message="No LLM validation report was produced.",
            ),
        ),
    )


def _raw_event(
    prompt_id: str,
    stage: str,
    status: str,
    model: str,
    *,
    round_index: int,
    response: dict[str, Any] | None = None,
    error: OpenRouterError | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": prompt_id,
        "stage": stage,
        "status": status,
        "model": model,
        "round": round_index,
    }
    if response is not None:
        event["response"] = response
    if error is not None:
        event["error"] = str(error)
        event["debug_payload"] = error.debug_payload
    return event
