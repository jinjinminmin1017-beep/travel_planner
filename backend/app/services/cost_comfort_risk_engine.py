from __future__ import annotations

from uuid import uuid4

from app.models.schemas import (
    ComfortScore,
    CostBreakdown,
    CostItem,
    DataQuality,
    DataSourceMetadata,
    FlightSegment,
    LocalTransferSegment,
    NormalizedScores,
    RailSegment,
    RiskAssessment,
    RiskItem,
    RiskLevel,
    TicketEnhancement,
    TravelPlan,
    money,
)

COMFORT_SCORE_VERSION = "comfort_score_v1"
RISK_SCORE_VERSION = "risk_assessment_v1"
COST_SCORE_VERSION = "cost_breakdown_v1"
DATA_QUALITY_VERSION = "data_quality_v1"


def calculate_cost_breakdown(segments: list[object], ticket: TicketEnhancement | None = None) -> CostBreakdown:
    items: list[CostItem] = []
    total = 0
    for segment in segments:
        amount = None
        source = None
        label = ""
        if isinstance(segment, LocalTransferSegment):
            amount = segment.estimated_cost
            source = segment.data_source
            transfer_mode = segment.transfer_mode.value if hasattr(segment.transfer_mode, "value") else str(segment.transfer_mode)
            label = f"{segment.origin} -> {segment.destination} {transfer_mode}"
        elif isinstance(segment, RailSegment):
            option = next(item for item in segment.seat_options if item.option_id == segment.selected_seat_option_id)
            amount = option.price
            source = option.data_source
            label = f"{segment.train_number} {option.seat_type}"
        elif isinstance(segment, FlightSegment):
            option = next(item for item in segment.cabin_options if item.option_id == segment.selected_cabin_option_id)
            amount = option.price
            source = option.data_source
            label = f"{segment.flight_number} {option.cabin_type}"
        if amount and source:
            total += amount.amount_minor
            items.append(CostItem(label=label, amount=amount, data_source=source))
    if ticket:
        total += ticket.extra_cost.amount_minor
        items.append(CostItem(label=f"票源增强 {ticket.grade} 档额外费用", amount=ticket.extra_cost, data_source=ticket.data_source))
    return CostBreakdown(total_cost=money(total), items=items)


def build_comfort_score(base_score: float, plan_name: str, risk_level: RiskLevel) -> ComfortScore:
    score = _clamp_score(base_score)
    confidence = 0.86 if risk_level != RiskLevel.LOW else 0.95
    if risk_level == RiskLevel.BLOCKED:
        confidence = 0.45
    return ComfortScore(
        total_score=score,
        breakdown={
            "换乘复杂度": _clamp_score(score + 0.2),
            "等待压力": _clamp_score(score),
            "时间友好度": _clamp_score(score - 0.3),
            "座席/舱位舒适度": _clamp_score(score + 0.4),
            "接驳便利性": _clamp_score(score + 0.1),
            "误车/误机风险": _clamp_score(score - 0.6),
            "行李友好度": _clamp_score(score + 0.2),
        },
        score_vector=NormalizedScores(cost=0.7, duration=0.7, comfort=score / 10, risk=0.8 if risk_level != RiskLevel.BLOCKED else 0.2),
        confidence=confidence,
        score_version=COMFORT_SCORE_VERSION,
        explanation=f"{plan_name} 的舒适度由接驳、换乘、座席/舱位和风险共同计算。",
    )


def build_risk_assessment(level: RiskLevel, title: str, message: str, data_source: DataSourceMetadata) -> RiskAssessment:
    return RiskAssessment(
        overall_risk_level=level,
        recommendation_allowed=level != RiskLevel.BLOCKED,
        risk_items=[
            RiskItem(
                risk_id=f"risk_{uuid4().hex[:8]}",
                risk_level=level,
                title=title,
                message=message,
                data_source=data_source,
            )
        ],
    )


def build_data_quality(level: RiskLevel, risk_message: str, missing_components: list[str] | None = None) -> DataQuality:
    if level == RiskLevel.LOW:
        completeness = 0.96
    elif level == RiskLevel.MEDIUM:
        completeness = 0.88
    elif level == RiskLevel.HIGH:
        completeness = 0.72
    else:
        completeness = 0.35
    missing = list(missing_components or ([] if level == RiskLevel.LOW else ["部分实时辅助数据缺失"]))
    warnings = [] if level == RiskLevel.LOW else [risk_message]
    return DataQuality(completeness_score=completeness, missing_components=missing, warnings=warnings)


def refresh_plan_cost_and_quality(plan: TravelPlan) -> None:
    plan.cost_breakdown = calculate_cost_breakdown(plan.segments, plan.ticket_enhancement)
    plan.total_duration_minutes = sum(segment.duration_minutes for segment in plan.segments)


def _clamp_score(value: float) -> float:
    return round(max(0, min(10, value)), 2)
