from __future__ import annotations

from dataclasses import dataclass

from app.models.schemas import PlanType, RiskLevel


@dataclass(frozen=True)
class FlightLegSpec:
    segment_id: str
    flight_number: str
    origin_airport: str
    destination_airport: str
    departure_hour: int
    departure_minute: int
    arrival_hour: int
    arrival_minute: int
    base_fare_minor: int
    previous_flight_risk_available: bool = True


@dataclass(frozen=True)
class FlightPlanSpec:
    plan_id: str
    plan_name: str
    plan_type: PlanType
    legs: list[FlightLegSpec]
    comfort_score: float
    risk_level: RiskLevel
    risk_title: str
    risk_message: str


def build_flight_plan_specs(route_key: str, start_airport: str, end_airport: str) -> list[FlightPlanSpec]:
    profile = _profile(route_key, start_airport, end_airport)
    return [
        _direct(profile),
        _transfer(profile),
        _multi_airport(profile),
    ]


def _direct(profile: dict) -> FlightPlanSpec:
    return FlightPlanSpec(
        plan_id=profile["ids"]["direct"],
        plan_name="打车 + 航班直飞 + 打车",
        plan_type=PlanType.DIRECT_FLIGHT,
        legs=[
            FlightLegSpec(
                "seg_flight_direct",
                profile["direct_flight"],
                profile["start"],
                profile["end"],
                11,
                20,
                13,
                0,
                68600,
            )
        ],
        comfort_score=8.8,
        risk_level=RiskLevel.LOW,
        risk_title="直飞舒适",
        risk_message="直飞减少铁路长途乘坐时间，但仍需预留值机安检时间；价格以 Amadeus Price 确认为准。",
    )


def _transfer(profile: dict) -> FlightPlanSpec:
    transfer_airport = profile["transfer_airport"]
    return FlightPlanSpec(
        plan_id=profile["ids"]["transfer"],
        plan_name="打车 + 航班中转 + 打车",
        plan_type=PlanType.TRANSFER_FLIGHT,
        legs=[
            FlightLegSpec("seg_flight_transfer_1", profile["transfer_flights"][0], profile["start"], transfer_airport, 10, 35, 12, 10, 35600, previous_flight_risk_available=False),
            FlightLegSpec("seg_flight_transfer_2", profile["transfer_flights"][1], transfer_airport, profile["end"], 14, 0, 15, 10, 29800),
        ],
        comfort_score=7.4,
        risk_level=RiskLevel.MEDIUM,
        risk_title="航班中转风险",
        risk_message=f"航班中转经过 {transfer_airport}，需关注跨航司衔接、重新安检、行李直挂和前序航班延误风险。",
    )


def _multi_airport(profile: dict) -> FlightPlanSpec:
    alternate_origin = profile["alternate_origin"]
    return FlightPlanSpec(
        plan_id=profile["ids"]["multi_airport"],
        plan_name="备选机场 + 航班直飞 + 打车",
        plan_type=PlanType.MULTI_AIRPORT_FLIGHT,
        legs=[
            FlightLegSpec(
                "seg_flight_multi_airport",
                profile["alternate_flight"],
                alternate_origin,
                profile["end"],
                12,
                45,
                14,
                35,
                72600,
            )
        ],
        comfort_score=7.6,
        risk_level=RiskLevel.MEDIUM,
        risk_title="多机场组合风险",
        risk_message=f"该方案改用 {alternate_origin} 出发，需额外核对接驳耗时、航站楼、托运行李和最终平台可售状态。",
    )


def _profile(route_key: str, start_airport: str, end_airport: str) -> dict:
    if route_key == "北京_广州":
        return {
            "start": start_airport,
            "end": end_airport,
            "direct_flight": "CZ3102",
            "transfer_airport": "武汉天河机场",
            "transfer_flights": ["CZ3131", "CZ3342"],
            "alternate_origin": "北京大兴机场",
            "alternate_flight": "CZ3110",
            "ids": {
                "direct": "plan_flight_direct_bg",
                "transfer": "plan_flight_transfer_bg",
                "multi_airport": "plan_flight_multi_airport_bg",
            },
        }
    return {
        "start": start_airport,
        "end": end_airport,
        "direct_flight": "MU5511",
        "transfer_airport": "济南遥墙机场",
        "transfer_flights": ["MU2101", "SC8720"],
        "alternate_origin": "上海浦东机场",
        "alternate_flight": "MU5525",
        "ids": {
            "direct": "plan_flight_direct_shqd",
            "transfer": "plan_flight_transfer_shqd",
            "multi_airport": "plan_flight_multi_airport_shqd",
        },
    }
