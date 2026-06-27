from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import PlanType, RecommendationEligibility, RiskLevel, TicketEnhancementGrade


@dataclass(frozen=True)
class RailLegSpec:
    segment_id: str
    train_number: str
    origin_station: str
    destination_station: str
    departure_hour: int
    departure_minute: int
    arrival_hour: int
    arrival_minute: int
    base_fare_minor: int
    stop_sequence: list[str]


@dataclass(frozen=True)
class TicketEnhancementSpec:
    enhancement_id: str
    grade: TicketEnhancementGrade
    actual_origin: str
    actual_destination: str
    ticket_origin: str
    ticket_destination: str
    ticket_covers_actual_route: bool
    requires_onboard_supplement: bool
    unused_distance_ratio: float
    extra_cost_minor: int
    extra_cost_ratio: float
    risk_level: RiskLevel
    recommendation_message: str


@dataclass(frozen=True)
class RailPlanSpec:
    plan_id: str
    plan_name: str
    plan_type: PlanType
    legs: list[RailLegSpec]
    comfort_score: float
    risk_level: RiskLevel
    risk_title: str
    risk_message: str
    ticket_enhancement: TicketEnhancementSpec | None = None
    eligibility: RecommendationEligibility = RecommendationEligibility.ELIGIBLE
    can_be_selected_by_llm: bool = True
    block_reason_code: str | None = None
    block_reason_message: str | None = None


def build_rail_plan_specs(route_key: str, start_station: str, end_station: str) -> list[RailPlanSpec]:
    profile = _profile(route_key, start_station, end_station)
    specs = [
        _direct(profile),
        _transfer(profile),
        _multi_transfer(profile),
    ]
    if route_key == "上海_青岛":
        specs.extend(_ticket_enhancement_specs(profile))
        specs.append(_blocked_safety_spec(profile))
    return specs


def _direct(profile: dict) -> RailPlanSpec:
    return RailPlanSpec(
        plan_id=profile["ids"]["direct"],
        plan_name="打车 + 高铁直达 + 打车",
        plan_type=PlanType.DIRECT_RAIL,
        legs=[
            RailLegSpec(
                "seg_rail_direct",
                profile["direct_train"],
                profile["start"],
                profile["end"],
                9,
                48,
                15,
                38,
                52600,
                [profile["start"], profile["primary_transfer"], profile["end"]],
            )
        ],
        comfort_score=7.9,
        risk_level=RiskLevel.LOW,
        risk_title="直达风险低",
        risk_message="直达高铁换乘少，接驳风险可控。",
    )


def _transfer(profile: dict) -> RailPlanSpec:
    transfer = profile["primary_transfer"]
    return RailPlanSpec(
        plan_id=profile["ids"]["transfer"],
        plan_name="打车 + 高铁中转 + 打车",
        plan_type=PlanType.TRANSFER_RAIL,
        legs=[
            RailLegSpec("seg_rail_transfer_1", "G102", profile["start"], transfer, 10, 15, 11, 55, 16800, [profile["start"], transfer]),
            RailLegSpec("seg_rail_transfer_2", "G268", transfer, profile["end"], 12, 35, 17, 10, 38600, [transfer, profile["end"]]),
        ],
        comfort_score=7.1,
        risk_level=RiskLevel.MEDIUM,
        risk_title="中转等待风险",
        risk_message=f"高铁中转需要在 {transfer} 关注站内换乘时间和行李负担。",
    )


def _multi_transfer(profile: dict) -> RailPlanSpec:
    first, second = profile["multi_transfers"]
    return RailPlanSpec(
        plan_id=profile["ids"]["multi_transfer"],
        plan_name="打车 + 多段高铁中转 + 打车",
        plan_type=PlanType.MULTI_TRANSFER_RAIL,
        legs=[
            RailLegSpec("seg_rail_multi_1", "G120", profile["start"], first, 9, 30, 11, 15, 15600, [profile["start"], first]),
            RailLegSpec("seg_rail_multi_2", "G266", first, second, 11, 55, 13, 20, 13600, [first, second]),
            RailLegSpec("seg_rail_multi_3", "G556", second, profile["end"], 14, 10, 17, 20, 23800, [second, profile["end"]]),
        ],
        comfort_score=6.8,
        risk_level=RiskLevel.MEDIUM,
        risk_title="多段中转风险",
        risk_message=f"多段中转经过 {first}、{second}，需额外关注站内换乘和误车风险。",
    )


def _ticket_enhancement_specs(profile: dict) -> list[RailPlanSpec]:
    start = profile["start"]
    end = profile["end"]
    primary = profile["primary_transfer"]
    return [
        RailPlanSpec(
            "plan_ticket_s_shqd",
            "高铁票源增强 S 档",
            PlanType.RAIL_TICKET_ENHANCEMENT,
            [RailLegSpec("seg_rail_ticket_s", "G236", start, end, 9, 20, 15, 5, 53600, ["苏州北", start, primary, end])],
            8.2,
            RiskLevel.LOW,
            "票源增强可控",
            "票面区间覆盖实际区间，不需要补票。",
            ticket_enhancement=TicketEnhancementSpec("enh_s", TicketEnhancementGrade.S, start, end, "苏州北", end, True, False, 0.16, 6800, 0.12, RiskLevel.LOW, "S 档票源增强：多买区间完整覆盖实际乘车区间。"),
        ),
        RailPlanSpec(
            "plan_ticket_a_shqd",
            "高铁票源增强 A 档备选",
            PlanType.RAIL_TICKET_ENHANCEMENT,
            [RailLegSpec("seg_rail_ticket_a", "G238", start, end, 10, 0, 15, 50, 53600, ["无锡东", start, primary, end, "潍坊北"])],
            7.8,
            RiskLevel.MEDIUM,
            "票源增强谨慎推荐",
            "额外费用和未乘坐比例较高，默认不作为主推荐。",
            ticket_enhancement=TicketEnhancementSpec("enh_a", TicketEnhancementGrade.A, start, end, "无锡东", "潍坊北", True, False, 0.31, 16800, 0.26, RiskLevel.MEDIUM, "A 档票源增强：默认作为备选展示。"),
            eligibility=RecommendationEligibility.NOT_RECOMMENDED,
            can_be_selected_by_llm=False,
            block_reason_code="TICKET_A_BACKUP_ONLY",
            block_reason_message="A 档票源增强默认作为备选，不进入主推荐。",
        ),
        RailPlanSpec(
            "plan_buy_short_shqd",
            "买短补长高风险备选",
            PlanType.RAIL_TICKET_ENHANCEMENT,
            [RailLegSpec("seg_rail_buy_short", "G240", start, end, 10, 40, 16, 10, 39600, [start, "潍坊北", end])],
            5.8,
            RiskLevel.HIGH,
            "买短补长高风险",
            "补票成功、席位、费用和出站结果均以铁路现场规则为准。",
            ticket_enhancement=TicketEnhancementSpec("enh_buy_short", TicketEnhancementGrade.NOT_RECOMMENDED, start, end, start, end, True, True, 0, 0, 0, RiskLevel.HIGH, "买短补长高风险方案，仅作为折叠备选。"),
            eligibility=RecommendationEligibility.NOT_RECOMMENDED,
            can_be_selected_by_llm=False,
            block_reason_code="BUY_SHORT_SUPPLEMENT_REQUIRED",
            block_reason_message="买短补长不得进入三张主推荐卡。",
        ),
    ]


def _blocked_safety_spec(profile: dict) -> RailPlanSpec:
    return RailPlanSpec(
        "plan_blocked_shqd",
        "安全关键数据缺失 BLOCKED",
        PlanType.TRANSFER_RAIL,
        [RailLegSpec("seg_rail_blocked", "G999", profile["start"], profile["end"], 11, 0, 15, 30, 30000, [profile["start"], profile["end"]])],
        4.0,
        RiskLevel.BLOCKED,
        "安全关键数据缺失",
        "站序或最小中转时间无法确认，方案被阻断。",
        eligibility=RecommendationEligibility.BLOCKED,
        can_be_selected_by_llm=False,
        block_reason_code="SAFETY_CRITICAL_MISSING",
        block_reason_message="安全关键数据缺失，不能进入推荐候选池。",
    )


def _profile(route_key: str, start_station: str, end_station: str) -> dict:
    if route_key == "北京_广州":
        return {
            "start": start_station,
            "end": end_station,
            "direct_train": "G79",
            "primary_transfer": "郑州东",
            "multi_transfers": ["石家庄", "郑州东"],
            "ids": {
                "direct": "plan_rail_direct_bg",
                "transfer": "plan_rail_transfer_bg",
                "multi_transfer": "plan_rail_multi_transfer_bg",
            },
        }
    return {
        "start": start_station,
        "end": end_station,
        "direct_train": "G234",
        "primary_transfer": "济南西",
        "multi_transfers": ["徐州东", "济南西"],
        "ids": {
            "direct": "plan_rail_direct_shqd",
            "transfer": "plan_rail_transfer_shqd",
            "multi_transfer": "plan_rail_multi_transfer_shqd",
        },
    }
