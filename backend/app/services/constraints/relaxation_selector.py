from __future__ import annotations

from uuid import uuid4

from app.models.schemas import (
    ConstraintAnalysis,
    ConstraintResultType,
    ConstraintType,
    CoverageItem,
    CoverageStatus,
    FlightSegment,
    RecommendationEligibility,
    RelaxationAlternative,
    RelaxationCategory,
    SourceFailure,
    TransportMode,
    TravelPlan,
)
from app.services.constraints.models import ConstraintEvaluationResult
from app.services.constraints.pareto import pareto_frontier, violation_metric
from app.services.constraints.transport_mode_calculator import main_transport_modes

TIME_CONSTRAINTS = {
    ConstraintType.LATEST_ARRIVAL,
    ConstraintType.EARLIEST_DEPARTURE,
    ConstraintType.ARRIVAL_TIME_WINDOW,
    ConstraintType.DEPARTURE_TIME_WINDOW,
}
BUDGET_CONSTRAINTS = {ConstraintType.MAX_TOTAL_COST}


def build_constraint_analysis(
    evaluations: list[ConstraintEvaluationResult],
    failures: list[SourceFailure],
) -> ConstraintAnalysis:
    safe = [item for item in evaluations if item.safe_for_relaxation and item.violations]
    coverage = _coverage(evaluations, failures)
    if not safe:
        return ConstraintAnalysis(
            result_type=ConstraintResultType.NO_SAFE_ALTERNATIVE,
            summary="没有找到满足全部要求且可安全展示的备选方案，请修改出行条件后重试。",
            coverage=coverage,
            alternatives=[],
        )
    frontier = pareto_frontier(safe)
    selected: list[tuple[RelaxationCategory, ConstraintEvaluationResult]] = []
    _select_track(selected, RelaxationCategory.CLOSEST_TO_TIME, frontier, TIME_CONSTRAINTS)
    _select_track(selected, RelaxationCategory.CLOSEST_TO_BUDGET, frontier, BUDGET_CONSTRAINTS)
    remaining = [item for item in frontier if item.plan.plan_id not in {picked.plan.plan_id for _, picked in selected}]
    if remaining:
        selected.append((RelaxationCategory.LEAST_BEHAVIOR_CHANGE, min(remaining, key=_behavior_key)))
    elif not selected and frontier:
        selected.append((RelaxationCategory.LEAST_BEHAVIOR_CHANGE, min(frontier, key=_behavior_key)))
    alternatives = [_alternative(category, item) for category, item in selected[:3]]
    return ConstraintAnalysis(
        result_type=ConstraintResultType.RELAXATION_AVAILABLE if alternatives else ConstraintResultType.NO_SAFE_ALTERNATIVE,
        summary=_summary(alternatives, coverage),
        coverage=coverage,
        alternatives=alternatives,
    )


def _select_track(selected, category, items, kinds) -> None:
    eligible = [item for item in items if any(violation.constraint_type in kinds for violation in item.violations)]
    if not eligible:
        return
    chosen = min(eligible, key=lambda item: (len(item.violations), violation_metric(item, {kind.value for kind in kinds}), -item.plan.data_quality.completeness_score, item.plan.plan_id))
    if chosen.plan.plan_id not in {item.plan.plan_id for _, item in selected}:
        selected.append((category, chosen))


def _behavior_key(item: ConstraintEvaluationResult) -> tuple:
    return (len({violation.constraint_type for violation in item.violations}), len(item.violations), -item.plan.data_quality.completeness_score, item.plan.plan_id)


def _alternative(category: RelaxationCategory, item: ConstraintEvaluationResult) -> RelaxationAlternative:
    safe_plan = item.plan.model_copy(update={
        "recommendation_eligibility": RecommendationEligibility.NOT_RECOMMENDED,
        "can_be_selected_by_llm": False,
        "booking_redirects": [],
    })
    return RelaxationAlternative(
        alternative_id=f"alt_{uuid4().hex[:12]}",
        category=category,
        plan=safe_plan,
        violations=list(item.violations),
        preserved_constraints=list(item.preserved_constraints),
    )


def _coverage(evaluations: list[ConstraintEvaluationResult], failures: list[SourceFailure]) -> list[CoverageItem]:
    modes = set()
    for item in evaluations:
        modes.update(main_transport_modes(item.plan))
    result = []
    for mode, source_marker, label in ((TransportMode.RAIL, "rail", "铁路"), (TransportMode.FLIGHT, "flight", "航班")):
        relevant_failures = [failure for failure in failures if source_marker in failure.source_id.lower() or any(source_marker.upper() in str(plan_type) for plan_type in failure.impacted_plan_types)]
        if mode in modes:
            status = CoverageStatus.VERIFIED
            message = f"{label}候选已完成有效查询。"
        elif relevant_failures:
            timed_out = any("TIMEOUT" in (failure.error_code or "").upper() for failure in relevant_failures)
            status = CoverageStatus.TIMEOUT if timed_out else CoverageStatus.FAILED
            message = f"{label}数据源{'查询超时' if timed_out else '查询失败'}，暂时无法确认。"
        else:
            status = CoverageStatus.UNAVAILABLE
            message = f"{label}数据源未启用或当前路线未覆盖。"
        result.append(CoverageItem(transport_mode=mode, status=status, message=message))
    return result


def _summary(alternatives: list[RelaxationAlternative], coverage: list[CoverageItem]) -> str:
    if not alternatives:
        return "没有找到满足全部要求且可安全展示的备选方案，请修改出行条件后重试。"
    first = alternatives[0]
    violation = first.violations[0]
    verified = [item.transport_mode for item in coverage if item.status == CoverageStatus.VERIFIED]
    all_complete = all(item.status in {CoverageStatus.VERIFIED, CoverageStatus.EMPTY} for item in coverage)
    if all_complete:
        scope = "所有已查询交通方式"
    elif verified == [TransportMode.RAIL]:
        scope = "当前已验证的铁路方案"
    elif verified == [TransportMode.FLIGHT]:
        scope = "当前已验证的航班方案"
    else:
        scope = "当前已验证方案"
    return f"没有找到满足全部约束的方案。{scope}中最近的安全备选：{violation.user_visible_message}"
