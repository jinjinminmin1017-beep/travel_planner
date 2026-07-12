from __future__ import annotations

from app.models.schemas import FlightSegment, RailSegment, RecommendationEligibility, RiskLevel, TravelPlan


def relaxation_safety_reason(plan: TravelPlan) -> str | None:
    if plan.risk_assessment.overall_risk_level == RiskLevel.BLOCKED:
        return "方案风险已阻断"
    if plan.recommendation_eligibility == RecommendationEligibility.BLOCKED:
        return "方案不允许推荐"
    if not plan.risk_assessment.recommendation_allowed:
        return "风险评估不允许展示"
    main_segments = [segment for segment in plan.segments if isinstance(segment, (RailSegment, FlightSegment))]
    if not main_segments:
        return "缺少可验证的铁路或航班主行程"
    if any(not segment.departure_time or not segment.arrival_time or not segment.data_source for segment in main_segments):
        return "主行程核心时间或来源不完整"
    if not plan.data_sources or plan.data_quality.completeness_score <= 0:
        return "方案数据来源或完整性不足"
    return None
