from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.15"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class TransportMode(str, Enum):
    RAIL = "RAIL"
    FLIGHT = "FLIGHT"
    TAXI = "TAXI"
    SUBWAY = "SUBWAY"
    BUS = "BUS"
    WALK = "WALK"
    AIRPORT_TRANSFER = "AIRPORT_TRANSFER"
    RAIL_STATION_TRANSFER = "RAIL_STATION_TRANSFER"


class PlanType(str, Enum):
    DIRECT_RAIL = "DIRECT_RAIL"
    TRANSFER_RAIL = "TRANSFER_RAIL"
    MULTI_TRANSFER_RAIL = "MULTI_TRANSFER_RAIL"
    RAIL_TICKET_ENHANCEMENT = "RAIL_TICKET_ENHANCEMENT"
    DIRECT_FLIGHT = "DIRECT_FLIGHT"
    TRANSFER_FLIGHT = "TRANSFER_FLIGHT"
    MULTI_AIRPORT_FLIGHT = "MULTI_AIRPORT_FLIGHT"
    FLIGHT_RAIL_MIXED = "FLIGHT_RAIL_MIXED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"


class PlanLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class PlanningStatus(str, Enum):
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class RecommendationEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    BLOCKED = "BLOCKED"


class RecommendationType(str, Enum):
    CHEAPEST = "CHEAPEST"
    MOST_COMFORTABLE = "MOST_COMFORTABLE"
    BALANCED = "BALANCED"


class RecommendationSource(str, Enum):
    LLM = "LLM"
    MOCK_LLM = "MOCK_LLM"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"


class RecommendationSlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BLOCKED = "BLOCKED"


class TicketEnhancementGrade(str, Enum):
    S = "S"
    A = "A"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    BLOCKED = "BLOCKED"


class SourceFailureClass(str, Enum):
    AUXILIARY = "AUXILIARY"
    FALLBACK_USED = "FALLBACK_USED"
    CORE_FACT = "CORE_FACT"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"


class SourceFailureHandlingStrategy(str, Enum):
    USE_ORIGINAL = "USE_ORIGINAL"
    USE_FALLBACK = "USE_FALLBACK"
    PARTIAL_RESULT = "PARTIAL_RESULT"
    BLOCK_PLAN_TYPE = "BLOCK_PLAN_TYPE"


class DataSourceType(str, Enum):
    MOCK = "MOCK"
    MAP = "MAP"
    RAIL = "RAIL"
    FLIGHT = "FLIGHT"
    TAXI = "TAXI"
    OTA = "OTA"
    LLM = "LLM"
    INTERNAL_CALCULATION = "INTERNAL_CALCULATION"


class Money(StrictModel):
    amount_minor: int = Field(ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    scale: int = Field(default=2, ge=0, le=6)
    is_estimated: bool = False
    display_text: str

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class MoneyDelta(StrictModel):
    amount_minor: int
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    scale: int = Field(default=2, ge=0, le=6)
    display_text: str


class TimePoint(StrictModel):
    datetime: datetime
    timezone: str = "Asia/Shanghai"
    source_timezone: str = "Asia/Shanghai"


class GeoPoint(StrictModel):
    latitude: float
    longitude: float
    coordinate_system: str = "MOCK_WGS84"


class NormalizedScores(StrictModel):
    cost: float = Field(ge=0, le=1)
    duration: float = Field(ge=0, le=1)
    comfort: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)


class CacheMetadata(StrictModel):
    cacheable: bool
    cache_ttl_seconds: int | None = None
    cache_hit: bool = False


class DataSourceMetadata(StrictModel):
    source_id: str
    source_name: str
    source_type: DataSourceType
    authority_level: Literal["S", "A", "B", "C"]
    license_status: Literal["APPROVED", "PENDING_REVIEW", "REJECTED"]
    commercial_allowed: bool
    fetched_at: TimePoint
    update_frequency: str
    cacheable: bool


class DataSourceConfig(StrictModel):
    source_id: str
    source_name: str
    source_type: DataSourceType
    authority_level: Literal["S", "A", "B", "C"]
    environment: Literal["DEV", "TEST", "PROD"]
    license_status: Literal["APPROVED", "PENDING_REVIEW", "REJECTED"]
    commercial_allowed: bool
    enabled: bool
    qps_limit: int = Field(ge=0)
    sla_level: str
    fallback_source_id: str | None = None
    last_checked_at: TimePoint | None = None


class SourceFailure(StrictModel):
    failure_id: str
    request_id: str
    trace_id: str
    correlation_id: str
    source_id: str
    source_used_id: str | None = None
    fallback_source_id: str | None = None
    fallback_reason: str | None = None
    fallback_used: bool
    failure_class: SourceFailureClass
    message: str
    final_handling_strategy: SourceFailureHandlingStrategy
    impacted_plan_types: list[PlanType]
    user_visible_message: str
    occurred_at: TimePoint


class DataSourceRuntimeStatus(StrictModel):
    source_id: str
    source_name: str
    source_type: DataSourceType
    enabled: bool
    status: Literal["OK", "DEGRADED", "DOWN"]
    degraded: bool
    degraded_reason: str | None = None
    last_success_at: TimePoint | None = None
    last_failure_at: TimePoint | None = None
    latest_failure: SourceFailure | None = None
    average_latency_ms: int | None = None
    checked_at: TimePoint


class ErrorResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    error_code: str
    message: str
    user_visible_message: str
    retryable: bool
    details: dict[str, Any] | None
    generated_at: TimePoint


class TravelHardConstraints(StrictModel):
    latest_arrival_time: TimePoint | None = None
    earliest_departure_time: TimePoint | None = None
    max_total_cost: Money | None = None
    allowed_transport_modes: list[TransportMode] = Field(default_factory=list)
    excluded_transport_modes: list[TransportMode] = Field(default_factory=list)


class TravelSoftPreferences(StrictModel):
    prefer_low_cost: bool = False
    prefer_comfort: bool = False
    accept_rail_transfer: bool = True
    accept_flight_transfer: bool = True
    accept_mixed_transport: bool = True
    accept_ticket_enhancement: bool = True
    passenger_notes: list[str] = Field(default_factory=list)


class TravelRequest(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    raw_user_input: str
    origin_text: str
    destination_text: str
    travel_date: date
    earliest_departure_time: TimePoint | None = None
    latest_arrival_time: TimePoint | None = None
    preferred_departure_time: TimePoint | None = None
    preferences: list[RecommendationType]
    preference_source: Literal["SYSTEM_DEFAULT", "USER_EXPLICIT"] = "SYSTEM_DEFAULT"
    hard_constraints: TravelHardConstraints
    soft_preferences: TravelSoftPreferences
    preferred_rail_seat: str | None = None
    preferred_flight_cabin: str | None = None


class ParseTravelRequestBody(StrictModel):
    raw_user_input: str


class PlanRequest(StrictModel):
    raw_user_input: str | None = None
    travel_request: TravelRequest | None = None

    @model_validator(mode="after")
    def require_input(self) -> "PlanRequest":
        if not self.raw_user_input and not self.travel_request:
            raise ValueError("raw_user_input or travel_request is required")
        return self


class StationCandidate(StrictModel):
    station_id: str
    station_name: str
    city_name: str
    location: GeoPoint
    estimated_transfer_duration_minutes: int
    estimated_transfer_cost: Money | None
    ranking_reasons: list[str]
    data_source: DataSourceMetadata


class AirportCandidate(StrictModel):
    airport_id: str
    airport_name: str
    city_name: str
    location: GeoPoint
    estimated_transfer_duration_minutes: int
    estimated_transfer_cost: Money | None
    ranking_reasons: list[str]
    data_source: DataSourceMetadata


class BookingRedirect(StrictModel):
    redirect_id: str
    redirect_type: Literal["RAIL_12306", "AIRLINE", "OTA", "MAP_NAVIGATION", "RIDE_HAILING"]
    transaction_boundary: Literal["REDIRECT_ONLY"] = "REDIRECT_ONLY"
    url_available: bool
    url: str | None = None
    fallback_instruction: str | None = None
    data_source: DataSourceMetadata
    generated_at: TimePoint
    expires_at: TimePoint | None = None


class SeatOption(StrictModel):
    option_id: str
    seat_type: str
    price: Money
    availability: str
    source_option_version: str
    data_source: DataSourceMetadata


class CabinOption(StrictModel):
    option_id: str
    cabin_type: str
    price: Money
    availability: str
    source_option_version: str
    data_source: DataSourceMetadata


class LocalTransferSegment(StrictModel):
    segment_id: str
    segment_type: Literal["LOCAL_TRANSFER"] = "LOCAL_TRANSFER"
    origin: str
    destination: str
    transfer_mode: TransportMode
    distance_meters: int
    duration_minutes: int
    estimated_cost: Money
    traffic_risk: RiskLevel
    walking_distance_meters: int
    option_id: str
    available_options: list[str] = Field(default_factory=list)
    data_source: DataSourceMetadata
    redirect_info: BookingRedirect | None = None


class RailSegment(StrictModel):
    segment_id: str
    segment_type: Literal["RAIL"] = "RAIL"
    train_number: str
    origin_station: str
    destination_station: str
    departure_time: TimePoint
    arrival_time: TimePoint
    duration_minutes: int
    stop_sequence: list[str]
    seat_options: list[SeatOption] = Field(min_length=1)
    selected_seat_option_id: str
    data_source: DataSourceMetadata


class FlightSegment(StrictModel):
    segment_id: str
    segment_type: Literal["FLIGHT"] = "FLIGHT"
    flight_number: str
    origin_airport: str
    destination_airport: str
    departure_time: TimePoint
    arrival_time: TimePoint
    duration_minutes: int
    cabin_options: list[CabinOption] = Field(min_length=1)
    selected_cabin_option_id: str
    previous_flight_risk_available: bool
    data_source: DataSourceMetadata


Segment = LocalTransferSegment | RailSegment | FlightSegment


class TicketEnhancement(StrictModel):
    enhancement_id: str
    grade: TicketEnhancementGrade
    actual_origin: str
    actual_destination: str
    ticket_origin: str
    ticket_destination: str
    ticket_covers_actual_route: bool
    requires_onboard_supplement: bool
    unused_distance_ratio: float = Field(ge=0)
    extra_cost: Money
    extra_cost_ratio: float = Field(ge=0)
    risk_level: RiskLevel
    recommendation_message: str
    validation_source: str
    validation_rule_version: str
    data_source: DataSourceMetadata


class CostItem(StrictModel):
    label: str
    amount: Money
    data_source: DataSourceMetadata


class CostBreakdown(StrictModel):
    total_cost: Money
    items: list[CostItem]


class ComfortScore(StrictModel):
    total_score: float = Field(ge=0, le=10)
    breakdown: dict[str, float]
    score_vector: NormalizedScores
    confidence: float = Field(ge=0, le=1)
    explanation: str


class RiskItem(StrictModel):
    risk_id: str
    risk_level: RiskLevel
    title: str
    message: str
    data_source: DataSourceMetadata


class RiskAssessment(StrictModel):
    overall_risk_level: RiskLevel
    recommendation_allowed: bool
    risk_items: list[RiskItem]


class DataQuality(StrictModel):
    completeness_score: float = Field(ge=0, le=1)
    missing_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TravelPlan(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    plan_id: str
    plan_name: str
    plan_type: PlanType
    plan_lifecycle_status: PlanLifecycleStatus
    recommendation_eligibility: RecommendationEligibility
    can_be_selected_by_llm: bool
    block_reason_code: str | None = None
    block_reason_message: str | None = None
    segments: list[Segment]
    ticket_enhancement: TicketEnhancement | None = None
    total_duration_minutes: int
    departure_time: TimePoint | None = None
    arrival_time: TimePoint | None = None
    cost_breakdown: CostBreakdown
    comfort_score: ComfortScore
    risk_assessment: RiskAssessment
    data_quality: DataQuality
    data_sources: list[DataSourceMetadata] = Field(min_length=1)
    booking_redirects: list[BookingRedirect] = Field(default_factory=list)


class RecommendationSlot(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    recommendation_type: RecommendationType
    status: RecommendationSlotStatus
    plan_id: str | None
    reason: str

    @model_validator(mode="after")
    def validate_status(self) -> "RecommendationSlot":
        if self.status == RecommendationSlotStatus.AVAILABLE and not self.plan_id:
            raise ValueError("plan_id is required for AVAILABLE recommendations")
        if self.status != RecommendationSlotStatus.AVAILABLE and self.plan_id is not None:
            raise ValueError("plan_id must be null for unavailable recommendations")
        if not self.reason:
            raise ValueError("reason is required")
        return self


class LLMRecommendationInput(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    travel_request: TravelRequest
    candidate_plan_ids: list[str] = Field(min_length=1, max_length=15)
    candidate_plans: list[TravelPlan] = Field(min_length=1, max_length=15)


class LLMRecommendationOutput(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    selected_recommendations: list[RecommendationSlot] = Field(min_length=3, max_length=3)
    validation_blockers: list[str] = Field(default_factory=list)
    explanation: str


class LLMValidationResult(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    schema_valid: bool
    semantic_valid: bool
    repair_attempted: bool
    final_strategy: Literal["USE_ORIGINAL", "REPAIRED", "DETERMINISTIC_FALLBACK", "REJECTED"]
    invalid_reasons: list[str] = Field(default_factory=list)


class RecommendationResult(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    recommendation_id: str
    recommendation_source: RecommendationSource
    recommendations: list[RecommendationSlot] = Field(min_length=3, max_length=3)
    llm_validation_result: LLMValidationResult


class ParseTravelRequestResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    travel_request: TravelRequest
    generated_at: TimePoint


class MissingPlanExplanation(StrictModel):
    plan_type: PlanType
    reason_code: str
    user_visible_message: str


class TravelPlanResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    planning_status: PlanningStatus
    progress: int = Field(ge=0, le=100)
    travel_request: TravelRequest
    plans: list[TravelPlan]
    recommendation_result: RecommendationResult | None
    source_failures: list[SourceFailure]
    missing_components: list[str]
    blocked_plan_types: list[PlanType]
    missing_plan_explanations: list[MissingPlanExplanation]
    user_visible_warnings: list[str]
    async_job: dict[str, Any] | None = None
    generated_at: TimePoint


class GetTravelPlanResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    plan: TravelPlan
    generated_at: TimePoint


class SelectedOption(StrictModel):
    option_type: Literal["RAIL_SEAT", "FLIGHT_CABIN", "LOCAL_TRANSFER"]
    option_id: str
    option_value: str
    source_option_version: str


class RecalculateRequest(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    idempotency_key: str
    plan_id: str
    change_type: Literal["RAIL_SEAT", "FLIGHT_CABIN", "LOCAL_TRANSFER"]
    target_segment_id: str
    selected_option: SelectedOption
    recalculate_scope: Literal["SEGMENT_ONLY", "PLAN_TOTAL"] = "PLAN_TOTAL"

    @model_validator(mode="after")
    def change_matches_option(self) -> "RecalculateRequest":
        if self.change_type != self.selected_option.option_type:
            raise ValueError("change_type must match selected_option.option_type")
        return self


class RecalculateChangeSummary(StrictModel):
    cost_delta: MoneyDelta
    duration_delta_minutes: int
    comfort_delta: float
    changed_fields: list[str]
    message: str


class RecalculateResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    plan: TravelPlan
    change_summary: RecalculateChangeSummary
    recommendation_result: RecommendationResult | None = None
    generated_at: TimePoint


class BookingRedirectRequest(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    idempotency_key: str
    plan_id: str
    segment_id: str | None = None
    redirect_type: Literal["RAIL_12306", "AIRLINE", "OTA", "MAP_NAVIGATION", "RIDE_HAILING"]


class BookingRedirectResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    redirect: BookingRedirect
    generated_at: TimePoint


class HealthResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    status: Literal["OK", "DEGRADED", "DOWN"]
    service_name: str
    version: str
    checked_at: TimePoint


class DataSourceStatusResponse(StrictModel):
    schema_version: Literal["1.15"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    sources: list[DataSourceRuntimeStatus]
    generated_at: TimePoint


def now_timepoint() -> TimePoint:
    return TimePoint(datetime=datetime.now(timezone.utc).astimezone(), timezone="Asia/Shanghai", source_timezone="Asia/Shanghai")


def money(amount_minor: int, estimated: bool = False) -> Money:
    sign = "-" if amount_minor < 0 else ""
    value = abs(amount_minor) / 100
    return Money(amount_minor=amount_minor, currency="CNY", scale=2, is_estimated=estimated, display_text=f"{sign}¥{value:.2f}")


def money_delta(amount_minor: int) -> MoneyDelta:
    sign = "-" if amount_minor < 0 else "+"
    value = abs(amount_minor) / 100
    return MoneyDelta(amount_minor=amount_minor, currency="CNY", scale=2, display_text=f"{sign}¥{value:.2f}")
