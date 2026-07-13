from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.17"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class TransportMode(str, Enum):
    RAIL = "RAIL"
    FLIGHT = "FLIGHT"
    TAXI = "TAXI"
    RIDE_HAILING = "RIDE_HAILING"
    SUBWAY = "SUBWAY"
    BUS = "BUS"
    WALK = "WALK"
    AIRPORT_TRANSFER = "AIRPORT_TRANSFER"
    RAIL_STATION_TRANSFER = "RAIL_STATION_TRANSFER"
    MIXED = "MIXED"


class PlanType(str, Enum):
    DIRECT_RAIL = "DIRECT_RAIL"
    TRANSFER_RAIL = "TRANSFER_RAIL"
    MULTI_TRANSFER_RAIL = "MULTI_TRANSFER_RAIL"
    RAIL_TICKET_ENHANCEMENT = "RAIL_TICKET_ENHANCEMENT"
    DIRECT_FLIGHT = "DIRECT_FLIGHT"
    TRANSFER_FLIGHT = "TRANSFER_FLIGHT"
    MULTI_AIRPORT_FLIGHT = "MULTI_AIRPORT_FLIGHT"
    FLIGHT_RAIL_MIXED = "FLIGHT_RAIL_MIXED"
    GROUND_ONLY = "GROUND_ONLY"
    MIXED = "MIXED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"


class PlanLifecycleStatus(str, Enum):
    GENERATED = "GENERATED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    BOOKED = "BOOKED"


class PlanningStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    NO_MATCH = "NO_MATCH"
    FAILED = "FAILED"


class AsyncJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_SOURCE = "WAITING_SOURCE"
    PARTIAL_READY = "PARTIAL_READY"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RecommendationEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    BLOCKED = "BLOCKED"


class ConstraintResultType(str, Enum):
    RELAXATION_AVAILABLE = "RELAXATION_AVAILABLE"
    NO_SAFE_ALTERNATIVE = "NO_SAFE_ALTERNATIVE"


class CoverageStatus(str, Enum):
    VERIFIED = "VERIFIED"
    EMPTY = "EMPTY"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class RelaxationCategory(str, Enum):
    CLOSEST_TO_TIME = "CLOSEST_TO_TIME"
    CLOSEST_TO_BUDGET = "CLOSEST_TO_BUDGET"
    LEAST_BEHAVIOR_CHANGE = "LEAST_BEHAVIOR_CHANGE"


class ConstraintType(str, Enum):
    LATEST_ARRIVAL = "LATEST_ARRIVAL"
    EARLIEST_DEPARTURE = "EARLIEST_DEPARTURE"
    ARRIVAL_TIME_WINDOW = "ARRIVAL_TIME_WINDOW"
    DEPARTURE_TIME_WINDOW = "DEPARTURE_TIME_WINDOW"
    MAX_TOTAL_COST = "MAX_TOTAL_COST"
    ALLOWED_TRANSPORT_MODES = "ALLOWED_TRANSPORT_MODES"
    EXCLUDED_TRANSPORT_MODES = "EXCLUDED_TRANSPORT_MODES"
    PREFERRED_RAIL_SEAT = "PREFERRED_RAIL_SEAT"
    PREFERRED_FLIGHT_CABIN = "PREFERRED_FLIGHT_CABIN"


class RecommendationType(str, Enum):
    CHEAPEST = "CHEAPEST"
    MOST_COMFORTABLE = "MOST_COMFORTABLE"
    BALANCED = "BALANCED"


class RecommendationSource(str, Enum):
    LLM = "LLM"


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
    AUXILIARY_DATA_FAILURE = "AUXILIARY_DATA_FAILURE"
    FALLBACK_AVAILABLE_FAILURE = "FALLBACK_AVAILABLE_FAILURE"
    CORE_FACT_FAILURE = "CORE_FACT_FAILURE"
    SAFETY_CRITICAL_FAILURE = "SAFETY_CRITICAL_FAILURE"


class SourceFailureHandlingStrategy(str, Enum):
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"
    PARTIAL_RESULT = "PARTIAL_RESULT"
    DEGRADE_CONFIDENCE = "DEGRADE_CONFIDENCE"
    BLOCK_PLAN = "BLOCK_PLAN"
    EXPLAIN_ONLY = "EXPLAIN_ONLY"
    LOG_ONLY = "LOG_ONLY"


class DataSourceType(str, Enum):
    MAP = "MAP"
    RAIL = "RAIL"
    FLIGHT = "FLIGHT"
    WEATHER = "WEATHER"
    TAXI = "TAXI"
    LLM = "LLM"
    INTERNAL_CALCULATION = "INTERNAL_CALCULATION"


class Money(StrictModel):
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    scale: int = Field(ge=0, le=6)
    is_estimated: bool = False
    display_text: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class MoneyDelta(StrictModel):
    amount_minor: int
    currency: str = Field(min_length=3, max_length=3)
    scale: int = Field(ge=0, le=6)
    display_text: str | None = None


class TimePoint(StrictModel):
    datetime: datetime
    timezone: str
    source_timezone: str | None = None

    @model_validator(mode="after")
    def normalize_timezone(self) -> "TimePoint":
        timezone_name = self.timezone.strip()
        if not timezone_name:
            raise ValueError("timezone must be a non-empty IANA timezone")
        try:
            target_timezone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"timezone must be a valid IANA timezone: {timezone_name}") from exc

        normalized_datetime = self.datetime
        if normalized_datetime.tzinfo is None or normalized_datetime.utcoffset() is None:
            normalized_datetime = normalized_datetime.replace(tzinfo=target_timezone)
        else:
            normalized_datetime = normalized_datetime.astimezone(target_timezone)

        self.datetime = normalized_datetime
        self.timezone = timezone_name
        if not self.source_timezone:
            self.source_timezone = timezone_name
        return self


class GeoPoint(StrictModel):
    name: str
    latitude: float | None = None
    longitude: float | None = None


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
    source_priority: int | None = Field(default=None, ge=0)
    source_region: str | None = None
    api_version: str | None = None
    license_status: Literal["APPROVED", "PENDING_REVIEW", "NOT_APPROVED"]
    commercial_allowed: bool
    fetched_at: TimePoint
    data_freshness_seconds: int | None = Field(default=None, ge=0)
    cacheable: bool
    cache_ttl_seconds: int | None = Field(default=None, ge=0)
    sla_level: str | None = None
    cache_metadata: CacheMetadata | None = None


class DataSourceConfig(StrictModel):
    source_id: str
    source_name: str
    source_type: DataSourceType
    authority_level: Literal["S", "A", "B", "C"]
    environment: Literal["DEV", "TEST", "PROD"]
    license_status: Literal["APPROVED", "PENDING_REVIEW", "NOT_APPROVED"]
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
    adapter_name: str
    handling_strategy: SourceFailureHandlingStrategy
    error_code: str | None
    retry_count: int = Field(ge=0)
    source_used_id: str | None
    fallback_source_id: str | None
    fallback_reason: str | None
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
    health_status: Literal["OK", "DEGRADED", "DOWN", "DISABLED"]
    degraded_reason: str | None = None
    authority_level: Literal["S", "A", "B", "C"] | None = None
    license_status: Literal["APPROVED", "PENDING_REVIEW", "NOT_APPROVED"] | None = None
    commercial_allowed: bool | None = None
    last_success_at: TimePoint | None = None
    last_failure_at: TimePoint | None = None
    latest_failure: SourceFailure | None = None
    average_latency_ms: int | None = None
    checked_at: TimePoint


class ErrorResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
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
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    raw_user_input: str
    origin_text: str
    destination_text: str
    travel_date: date
    time_anchor_type: Literal["DEPARTURE", "ARRIVAL", "AMBIGUOUS"] = "DEPARTURE"
    time_window_start: TimePoint | None = None
    time_window_end: TimePoint | None = None
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
    redirect_type: Literal["RAIL_12306", "AIRLINE", "MAP_NAVIGATION", "RIDE_HAILING"]
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


class LocalTransferOption(StrictModel):
    option_id: str
    transfer_mode: TransportMode
    label: str
    estimated_cost: Money
    duration_minutes: int
    distance_meters: int | None = None
    access_station: str | None = None
    egress_station: str | None = None
    access_instruction: str
    ride_instruction: str
    egress_instruction: str
    walking_distance_meters: int | None = None
    data_source: DataSourceMetadata
    route_status: Literal["PRIMARY_VERIFIED", "FALLBACK_VERIFIED", "RULE_ESTIMATED", "UNAVAILABLE"] = "PRIMARY_VERIFIED"
    route_error_code: str | None = None


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
    walking_distance_meters: int | None = None
    option_id: str
    available_options: list[str] = Field(default_factory=list)
    transfer_options: list[LocalTransferOption] = Field(default_factory=list)
    departure_time: TimePoint | None = None
    arrival_time: TimePoint | None = None
    data_source: DataSourceMetadata
    route_status: Literal["PRIMARY_VERIFIED", "FALLBACK_VERIFIED", "RULE_ESTIMATED", "UNAVAILABLE"] = "PRIMARY_VERIFIED"
    route_error_code: str | None = None
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
    score_version: str = "comfort_score_v1"
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
    schema_version: Literal["1.17"] = SCHEMA_VERSION
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
    schema_version: Literal["1.17"] = SCHEMA_VERSION
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
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    travel_request: TravelRequest
    candidate_plan_ids: list[str] = Field(min_length=1, max_length=15)
    candidate_plans: list[TravelPlan] = Field(min_length=1, max_length=15)


class LLMRecommendationOutput(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    selected_recommendations: list[RecommendationSlot] = Field(min_length=3, max_length=3)
    validation_blockers: list[str] = Field(default_factory=list)
    explanation: str


class LLMValidationResult(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    schema_valid: bool
    semantic_valid: bool
    repair_attempted: bool
    final_strategy: Literal["USE_ORIGINAL", "REPAIRED", "REJECTED", "FALLBACK_RULES"]
    invalid_reasons: list[str] = Field(default_factory=list)
    repair_success: bool | None = None
    llm_call_id: str | None = None
    prompt_version: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None


class RecommendationResult(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    recommendation_id: str
    recommendation_source: RecommendationSource
    recommendations: list[RecommendationSlot] = Field(min_length=3, max_length=3)
    llm_validation_result: LLMValidationResult


class ParseTravelRequestResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    travel_request: TravelRequest
    llm_validation_result: LLMValidationResult
    generated_at: TimePoint


class MissingPlanExplanation(StrictModel):
    plan_type: PlanType
    reason_code: str
    user_visible_message: str


class DurationDeviation(StrictModel):
    kind: Literal["DURATION"] = "DURATION"
    value: int = Field(ge=0)
    unit: Literal["MINUTE"] = "MINUTE"
    direction: Literal["EARLIER", "LATER"]


class MoneyDeviation(StrictModel):
    kind: Literal["MONEY"] = "MONEY"
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    scale: int = Field(ge=0, le=6)


class ModeSetDeviation(StrictModel):
    kind: Literal["MODE_SET"] = "MODE_SET"
    added_modes: list[TransportMode] = Field(default_factory=list)
    removed_modes: list[TransportMode] = Field(default_factory=list)


class CategoricalDeviation(StrictModel):
    kind: Literal["CATEGORICAL"] = "CATEGORICAL"
    requested: str
    actual: str


ConstraintDeviation = DurationDeviation | MoneyDeviation | ModeSetDeviation | CategoricalDeviation


class ConstraintViolation(StrictModel):
    constraint_type: ConstraintType
    relaxation_policy: Literal["USER_CONFIRMATION_REQUIRED"] = "USER_CONFIRMATION_REQUIRED"
    requested_value: dict[str, Any]
    actual_value: dict[str, Any]
    deviation: ConstraintDeviation
    reason_code: str
    user_visible_message: str


class CoverageItem(StrictModel):
    transport_mode: TransportMode
    status: CoverageStatus
    message: str


class RelaxationAlternative(StrictModel):
    alternative_id: str
    category: RelaxationCategory
    plan: TravelPlan
    violations: list[ConstraintViolation] = Field(min_length=1)
    preserved_constraints: list[ConstraintType] = Field(default_factory=list)
    user_confirmation_required: Literal[True] = True


class ConstraintAnalysis(StrictModel):
    result_type: ConstraintResultType
    summary: str
    coverage: list[CoverageItem]
    alternatives: list[RelaxationAlternative] = Field(max_length=3)


class DestinationPresentation(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    destination_key: str
    display_name: str
    hero_image_url: str
    image_alt: str
    image_credit: str | None = None
    image_source: Literal["LOCAL_STATIC", "CLOUD_CDN", "REMOTE_URL"] = "LOCAL_STATIC"
    focal_point: str = "center"
    tags: list[str] = Field(default_factory=list)


class AsyncJob(StrictModel):
    job_id: str
    job_status: AsyncJobStatus
    created_at: TimePoint
    updated_at: TimePoint
    polling_url: str | None = None


class TravelPlanResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    planning_status: PlanningStatus
    progress: int = Field(ge=0, le=100)
    travel_request: TravelRequest
    destination_presentation: DestinationPresentation | None = None
    plans: list[TravelPlan]
    recommendation_result: RecommendationResult | None
    constraint_analysis: ConstraintAnalysis | None = None
    source_failures: list[SourceFailure]
    missing_components: list[str]
    blocked_plan_types: list[PlanType]
    missing_plan_explanations: list[MissingPlanExplanation]
    user_visible_warnings: list[str]
    async_job: AsyncJob | None = None
    generated_at: TimePoint

    @model_validator(mode="after")
    def validate_constraint_result(self) -> "TravelPlanResponse":
        if self.planning_status == PlanningStatus.NO_MATCH:
            if self.plans or self.recommendation_result is not None or self.constraint_analysis is None:
                raise ValueError("NO_MATCH requires empty plans, null recommendation_result and constraint_analysis")
        return self


class GetTravelPlanResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    plan: TravelPlan
    generated_at: TimePoint


class SelectedOption(StrictModel):
    option_type: Literal["SEAT", "CABIN", "TRANSFER_MODE"]
    option_id: str
    option_value: str
    source_option_version: str


class RecalculateRequest(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    idempotency_key: str
    plan_id: str
    change_type: Literal["SEAT_TYPE", "CABIN_TYPE", "LOCAL_TRANSFER_MODE"]
    target_segment_id: str
    selected_option: SelectedOption
    application_scope: Literal["TARGET_PLAN", "RESULT_SET"] = "TARGET_PLAN"
    recalculate_scope: Literal["PLAN_ONLY", "PLAN_AND_RECOMMENDATION", "FULL_REEVALUATION"] = "PLAN_ONLY"

    @model_validator(mode="after")
    def change_matches_option(self) -> "RecalculateRequest":
        expected_option_type = {
            "SEAT_TYPE": "SEAT",
            "CABIN_TYPE": "CABIN",
            "LOCAL_TRANSFER_MODE": "TRANSFER_MODE",
        }[self.change_type]
        if expected_option_type != self.selected_option.option_type:
            raise ValueError("change_type must match selected_option.option_type")
        if self.application_scope == "RESULT_SET" and self.change_type != "SEAT_TYPE":
            raise ValueError("RESULT_SET application_scope is only supported for SEAT_TYPE")
        return self


class RecalculateChangeSummary(StrictModel):
    cost_delta: MoneyDelta
    duration_delta_minutes: int
    comfort_delta: float
    changed_fields: list[str]
    message: str


class PreferenceApplication(StrictModel):
    preference_type: Literal["RAIL_SEAT"] = "RAIL_SEAT"
    canonical_value: str
    application_scope: Literal["RESULT_SET"] = "RESULT_SET"
    applied_plan_ids: list[str]
    unsupported_plan_ids: list[str]
    message: str


class RecalculateResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    plan: TravelPlan
    change_summary: RecalculateChangeSummary
    updated_response: TravelPlanResponse | None = None
    preference_application: PreferenceApplication | None = None
    recommendation_result: RecommendationResult | None = None
    generated_at: TimePoint


class BookingRedirectRequest(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    idempotency_key: str
    plan_id: str
    segment_id: str | None = None
    redirect_type: Literal["RAIL_12306", "AIRLINE", "MAP_NAVIGATION", "RIDE_HAILING"]


class BookingRedirectResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    redirect: BookingRedirect
    generated_at: TimePoint


class FeedbackRequest(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    request_id: str
    trace_id: str
    correlation_id: str
    plan_id: str
    source_id: str | None = None
    category: Literal["ROUTE_INACCURATE", "PRICE_INACCURATE", "REDIRECT_FAILED", "HARD_TO_UNDERSTAND", "OTHER"]
    message: str | None = Field(default=None, max_length=500)


class FeedbackResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    feedback_id: str
    request_id: str
    trace_id: str
    correlation_id: str
    plan_id: str
    source_id: str | None = None
    category: str
    category_count: int
    received_at: TimePoint


class AppEventRequest(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    event_type: Literal[
        "INPUT_SUBMITTED",
        "PLANNING_SUCCESS",
        "PLANNING_PARTIAL",
        "PLANNING_NO_MATCH",
        "RECOMMENDATION_CLICK",
        "REDIRECT_CLICK",
        "FEEDBACK_SUBMITTED",
        "RECENT_PLAN_VIEWED",
        "FAVORITE_TOGGLED",
        "TRIP_REMINDER_TOGGLED",
        "PRICE_STATUS_WATCH_TOGGLED",
        "PREFERENCE_UPDATED",
    ]
    request_id: str | None = None
    trace_id: str | None = None
    plan_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppEventResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    event_id: str
    event_type: str
    accepted: bool
    received_at: TimePoint


class HealthResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
    status: Literal["OK", "DEGRADED", "DOWN"]
    service_name: str
    version: str
    checked_at: TimePoint


class DataSourceStatusResponse(StrictModel):
    schema_version: Literal["1.17"] = SCHEMA_VERSION
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
