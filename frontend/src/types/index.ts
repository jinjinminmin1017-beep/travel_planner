export type Money = {
  amount_minor: number;
  currency: string;
  scale: number;
  is_estimated?: boolean;
  display_text: string | null;
};

export type TimePoint = {
  datetime: string;
  timezone: string;
  source_timezone: string;
};

export type DataSourceMetadata = {
  source_id: string;
  source_name: string;
  source_type: string;
  authority_level: string;
  source_priority?: number | null;
  source_region?: string | null;
  api_version?: string | null;
  license_status: string;
  commercial_allowed: boolean;
  fetched_at: TimePoint;
  data_freshness_seconds?: number | null;
  cacheable: boolean;
  cache_ttl_seconds?: number | null;
  sla_level?: string | null;
  cache_metadata?: Record<string, unknown> | null;
};

export type RecalculateChangeType = "SEAT_TYPE" | "CABIN_TYPE" | "LOCAL_TRANSFER_MODE";
export type SelectedOptionType = "SEAT" | "CABIN" | "TRANSFER_MODE";
export type RecalculateScope = "PLAN_ONLY" | "PLAN_AND_RECOMMENDATION" | "FULL_REEVALUATION";
export type DataSourceHealthStatus = "OK" | "DEGRADED" | "DOWN" | "DISABLED";
export type PlanningStatus = "PENDING" | "RUNNING" | "PARTIAL" | "COMPLETE" | "NO_MATCH" | "FAILED";
export type AsyncJobStatus = "QUEUED" | "RUNNING" | "WAITING_SOURCE" | "PARTIAL_READY" | "COMPLETE" | "FAILED" | "CANCELLED";
export type FeedbackCategory = "ROUTE_INACCURATE" | "PRICE_INACCURATE" | "REDIRECT_FAILED" | "HARD_TO_UNDERSTAND" | "OTHER";
export type AppEventType =
  | "INPUT_SUBMITTED"
  | "PLANNING_SUCCESS"
  | "PLANNING_PARTIAL"
  | "PLANNING_NO_MATCH"
  | "RECOMMENDATION_CLICK"
  | "REDIRECT_CLICK"
  | "FEEDBACK_SUBMITTED"
  | "RECENT_PLAN_VIEWED"
  | "FAVORITE_TOGGLED"
  | "TRIP_REMINDER_TOGGLED"
  | "PRICE_STATUS_WATCH_TOGGLED"
  | "PREFERENCE_UPDATED";

export type ErrorResponse = {
  schema_version: "1.17";
  request_id: string;
  error_code: string;
  message: string;
  user_visible_message: string;
  retryable: boolean;
  details: Record<string, unknown> | null;
  generated_at: TimePoint;
};

export type TravelRequest = {
  schema_version: "1.17";
  request_id: string;
  raw_user_input: string;
  origin_text: string;
  destination_text: string;
  travel_date: string;
  time_anchor_type?: "DEPARTURE" | "ARRIVAL" | "AMBIGUOUS";
  time_window_start?: TimePoint | null;
  time_window_end?: TimePoint | null;
  earliest_departure_time?: TimePoint | null;
  latest_arrival_time?: TimePoint | null;
  preferred_departure_time?: TimePoint | null;
  preferences: string[];
  preference_source: string;
  hard_constraints: {
    latest_arrival_time?: TimePoint | null;
    earliest_departure_time?: TimePoint | null;
    max_total_cost?: Money | null;
    allowed_transport_modes: string[];
    excluded_transport_modes: string[];
  };
  soft_preferences: Record<string, unknown>;
  preferred_rail_seat?: string | null;
  preferred_flight_cabin?: string | null;
};

export type LLMValidationResult = {
  schema_version: "1.17";
  schema_valid: boolean;
  semantic_valid: boolean;
  repair_attempted: boolean;
  final_strategy: "USE_ORIGINAL" | "REPAIRED" | "REJECTED" | "FALLBACK_RULES";
  invalid_reasons: string[];
  repair_success?: boolean | null;
  llm_call_id?: string | null;
  prompt_version?: string | null;
  model_name?: string | null;
  latency_ms?: number | null;
};

export type ParseTravelRequestResponse = {
  schema_version: "1.17";
  request_id: string;
  trace_id: string;
  correlation_id: string;
  idempotency_key: string;
  travel_request: TravelRequest;
  llm_validation_result: LLMValidationResult;
  generated_at: TimePoint;
};

export type SeatOption = {
  option_id: string;
  seat_type: string;
  price: Money;
  availability: string;
  source_option_version: string;
};

export type CabinOption = {
  option_id: string;
  cabin_type: string;
  price: Money;
  availability: string;
  source_option_version: string;
};

export type BookingRedirect = {
  redirect_id: string;
  redirect_type: string;
  transaction_boundary: "REDIRECT_ONLY";
  url_available: boolean;
  url: string | null;
  fallback_instruction: string | null;
  data_source: DataSourceMetadata;
  generated_at: TimePoint;
  expires_at: TimePoint | null;
};

export type TicketEnhancement = {
  enhancement_id: string;
  grade: "S" | "A" | "NOT_RECOMMENDED" | "BLOCKED";
  actual_origin: string;
  actual_destination: string;
  ticket_origin: string;
  ticket_destination: string;
  ticket_covers_actual_route: boolean;
  requires_onboard_supplement: boolean;
  unused_distance_ratio: number;
  extra_cost: Money;
  extra_cost_ratio: number;
  risk_level: string;
  recommendation_message: string;
  validation_source: string;
  validation_rule_version: string;
  data_source: DataSourceMetadata;
};

export type LocalTransferOption = {
  option_id: string;
  transfer_mode: string;
  label: string;
  estimated_cost: Money;
  duration_minutes: number;
  distance_meters?: number | null;
  access_station: string | null;
  egress_station: string | null;
  access_instruction: string;
  ride_instruction: string;
  egress_instruction: string;
  walking_distance_meters: number | null;
  data_source: DataSourceMetadata;
  route_status: "PRIMARY_VERIFIED" | "FALLBACK_VERIFIED" | "RULE_ESTIMATED" | "UNAVAILABLE";
  route_error_code: string | null;
};

export type Segment = {
  segment_id: string;
  segment_type: "LOCAL_TRANSFER" | "RAIL" | "FLIGHT";
  origin?: string;
  destination?: string;
  transfer_mode?: string;
  duration_minutes: number;
  estimated_cost?: Money;
  option_id?: string;
  available_options?: string[];
  transfer_options?: LocalTransferOption[];
  train_number?: string;
  origin_station?: string;
  destination_station?: string;
  flight_number?: string;
  origin_airport?: string;
  destination_airport?: string;
  departure_time?: TimePoint;
  arrival_time?: TimePoint;
  seat_options?: SeatOption[];
  selected_seat_option_id?: string;
  cabin_options?: CabinOption[];
  selected_cabin_option_id?: string;
  previous_flight_risk_available?: boolean;
  data_source: DataSourceMetadata;
  route_status?: "PRIMARY_VERIFIED" | "FALLBACK_VERIFIED" | "RULE_ESTIMATED" | "UNAVAILABLE";
  route_error_code?: string | null;
  redirect_info?: BookingRedirect | null;
};

export type CostBreakdown = {
  total_cost: Money;
  items: Array<{ label: string; amount: Money; data_source: DataSourceMetadata }>;
};

export type NormalizedScores = {
  cost: number;
  duration: number;
  comfort: number;
  risk: number;
};

export type ComfortScore = {
  total_score: number;
  breakdown: Record<string, number>;
  score_vector: NormalizedScores;
  confidence: number;
  score_version: string;
  explanation: string;
};

export type RiskAssessment = {
  overall_risk_level: string;
  recommendation_allowed: boolean;
  risk_items: Array<{ risk_id: string; risk_level: string; title: string; message: string; data_source?: DataSourceMetadata }>;
};

export type DataQuality = {
  completeness_score: number;
  missing_components: string[];
  warnings: string[];
};

export type TravelPlan = {
  schema_version: "1.17";
  plan_id: string;
  plan_name: string;
  plan_type: string;
  plan_lifecycle_status: string;
  recommendation_eligibility: string;
  can_be_selected_by_llm: boolean;
  block_reason_code: string | null;
  block_reason_message: string | null;
  segments: Segment[];
  ticket_enhancement?: TicketEnhancement | null;
  total_duration_minutes: number;
  departure_time?: TimePoint | null;
  arrival_time?: TimePoint | null;
  cost_breakdown: CostBreakdown;
  comfort_score: ComfortScore;
  risk_assessment: RiskAssessment;
  data_quality: DataQuality;
  data_sources: DataSourceMetadata[];
  booking_redirects: BookingRedirect[];
};

export type RecommendationSlot = {
  schema_version: "1.17";
  recommendation_type: "CHEAPEST" | "MOST_COMFORTABLE" | "BALANCED";
  status: "AVAILABLE" | "NOT_AVAILABLE" | "BLOCKED";
  plan_id: string | null;
  reason: string;
};

export type DestinationPresentation = {
  schema_version: "1.17";
  destination_key: string;
  display_name: string;
  hero_image_url: string;
  image_alt: string;
  image_credit: string | null;
  image_source: "LOCAL_STATIC" | "CLOUD_CDN" | "REMOTE_URL";
  focal_point: string;
  tags: string[];
};

export type SourceFailure = {
  failure_id: string;
  request_id: string;
  trace_id: string;
  correlation_id: string;
  source_id: string;
  source_used_id: string | null;
  fallback_reason: string | null;
  fallback_used: boolean;
  failure_class: string;
  message: string;
  final_handling_strategy: string;
  impacted_plan_types: string[];
  user_visible_message: string;
};

export type AsyncJob = {
  job_id: string;
  job_status: AsyncJobStatus;
  created_at: TimePoint;
  updated_at: TimePoint;
  polling_url: string | null;
};

export type ConstraintType =
  | "LATEST_ARRIVAL"
  | "EARLIEST_DEPARTURE"
  | "ARRIVAL_TIME_WINDOW"
  | "DEPARTURE_TIME_WINDOW"
  | "MAX_TOTAL_COST"
  | "ALLOWED_TRANSPORT_MODES"
  | "EXCLUDED_TRANSPORT_MODES"
  | "PREFERRED_RAIL_SEAT"
  | "PREFERRED_FLIGHT_CABIN";

export type ConstraintViolation = {
  constraint_type: ConstraintType;
  relaxation_policy: "USER_CONFIRMATION_REQUIRED";
  requested_value: Record<string, unknown>;
  actual_value: Record<string, unknown>;
  deviation:
    | { kind: "DURATION"; value: number; unit: "MINUTE"; direction: "EARLIER" | "LATER" }
    | { kind: "MONEY"; amount_minor: number; currency: string; scale: number }
    | { kind: "MODE_SET"; added_modes: string[]; removed_modes: string[] }
    | { kind: "CATEGORICAL"; requested: string; actual: string };
  reason_code: string;
  user_visible_message: string;
};

export type RelaxationAlternative = {
  alternative_id: string;
  category: "CLOSEST_TO_TIME" | "CLOSEST_TO_BUDGET" | "LEAST_BEHAVIOR_CHANGE";
  plan: TravelPlan;
  violations: ConstraintViolation[];
  preserved_constraints: ConstraintType[];
  user_confirmation_required: true;
};

export type ConstraintAnalysis = {
  result_type: "RELAXATION_AVAILABLE" | "NO_SAFE_ALTERNATIVE";
  summary: string;
  coverage: Array<{
    transport_mode: string;
    status: "VERIFIED" | "EMPTY" | "UNAVAILABLE" | "FAILED" | "TIMEOUT";
    message: string;
  }>;
  alternatives: RelaxationAlternative[];
};

export type TravelPlanResponse = {
  schema_version: "1.17";
  request_id: string;
  trace_id: string;
  correlation_id: string;
  idempotency_key: string;
  planning_status: PlanningStatus;
  progress: number;
  travel_request: TravelRequest;
  destination_presentation?: DestinationPresentation | null;
  plans: TravelPlan[];
  recommendation_result: { recommendations: RecommendationSlot[]; llm_validation_result: LLMValidationResult } | null;
  constraint_analysis?: ConstraintAnalysis | null;
  source_failures: SourceFailure[];
  missing_components: string[];
  blocked_plan_types: string[];
  user_visible_warnings: string[];
  async_job?: AsyncJob | null;
  generated_at: TimePoint;
};

export type RecalculateResponse = {
  schema_version: "1.17";
  request_id: string;
  trace_id: string;
  correlation_id: string;
  idempotency_key: string;
  plan: TravelPlan;
  change_summary: {
    cost_delta: { amount_minor: number; display_text: string };
    duration_delta_minutes: number;
    comfort_delta: number;
    changed_fields: string[];
    message: string;
  };
  updated_response: TravelPlanResponse | null;
  preference_application: {
    preference_type: "RAIL_SEAT";
    canonical_value: string;
    application_scope: "RESULT_SET";
    applied_plan_ids: string[];
    unsupported_plan_ids: string[];
    message: string;
  } | null;
  recommendation_result: { recommendations: RecommendationSlot[]; llm_validation_result: LLMValidationResult } | null;
  generated_at: TimePoint;
};

export type DataSourceStatusResponse = {
  schema_version: "1.17";
  sources: Array<{
    source_id: string;
    source_name: string;
    source_type: string;
    enabled: boolean;
    health_status: DataSourceHealthStatus;
    degraded_reason: string | null;
    authority_level: string | null;
    license_status: string | null;
    commercial_allowed: boolean | null;
    average_latency_ms: number | null;
  }>;
};

export type FeedbackResponse = {
  schema_version: "1.17";
  feedback_id: string;
  request_id: string;
  trace_id: string;
  correlation_id: string;
  plan_id: string;
  source_id: string | null;
  category: FeedbackCategory;
  category_count: number;
  received_at: TimePoint;
};
