export type Money = {
  amount_minor: number;
  currency: string;
  scale: number;
  is_estimated?: boolean;
  display_text: string;
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
  license_status: string;
  commercial_allowed: boolean;
  fetched_at: TimePoint;
  update_frequency: string;
  cacheable: boolean;
};

export type ErrorResponse = {
  schema_version: "1.15";
  request_id: string;
  error_code: string;
  message: string;
  user_visible_message: string;
  retryable: boolean;
  details: Record<string, unknown> | null;
  generated_at: TimePoint;
};

export type TravelRequest = {
  schema_version: "1.15";
  request_id: string;
  raw_user_input: string;
  origin_text: string;
  destination_text: string;
  travel_date: string;
  preferences: string[];
  preference_source: string;
  hard_constraints: Record<string, unknown>;
  soft_preferences: Record<string, unknown>;
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
};

export type LocalTransferOption = {
  option_id: string;
  transfer_mode: string;
  label: string;
  estimated_cost: Money;
  duration_minutes: number;
  access_station: string | null;
  egress_station: string | null;
  access_instruction: string;
  ride_instruction: string;
  egress_instruction: string;
  walking_distance_meters: number;
  data_source: DataSourceMetadata;
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
  data_source: DataSourceMetadata;
  redirect_info?: BookingRedirect | null;
};

export type CostBreakdown = {
  total_cost: Money;
  items: Array<{ label: string; amount: Money; data_source: DataSourceMetadata }>;
};

export type ComfortScore = {
  total_score: number;
  breakdown: Record<string, number>;
  confidence: number;
  explanation: string;
};

export type RiskAssessment = {
  overall_risk_level: string;
  recommendation_allowed: boolean;
  risk_items: Array<{ risk_id: string; risk_level: string; title: string; message: string }>;
};

export type DataQuality = {
  completeness_score: number;
  missing_components: string[];
  warnings: string[];
};

export type TravelPlan = {
  schema_version: "1.15";
  plan_id: string;
  plan_name: string;
  plan_type: string;
  recommendation_eligibility: string;
  can_be_selected_by_llm: boolean;
  block_reason_code: string | null;
  block_reason_message: string | null;
  segments: Segment[];
  total_duration_minutes: number;
  cost_breakdown: CostBreakdown;
  comfort_score: ComfortScore;
  risk_assessment: RiskAssessment;
  data_quality: DataQuality;
  data_sources: DataSourceMetadata[];
  booking_redirects: BookingRedirect[];
};

export type RecommendationSlot = {
  schema_version: "1.15";
  recommendation_type: "CHEAPEST" | "MOST_COMFORTABLE" | "BALANCED";
  status: "AVAILABLE" | "NOT_AVAILABLE" | "BLOCKED";
  plan_id: string | null;
  reason: string;
};

export type DestinationPresentation = {
  schema_version: "1.15";
  destination_key: string;
  display_name: string;
  hero_image_url: string;
  image_alt: string;
  image_credit: string | null;
  image_source: "LOCAL_STATIC" | "CLOUD_CDN" | "REMOTE_URL";
  focal_point: string;
  tags: string[];
};

export type TravelPlanResponse = {
  schema_version: "1.15";
  request_id: string;
  trace_id: string;
  correlation_id: string;
  idempotency_key: string;
  planning_status: string;
  progress: number;
  travel_request: TravelRequest;
  destination_presentation?: DestinationPresentation | null;
  plans: TravelPlan[];
  recommendation_result: { recommendations: RecommendationSlot[]; llm_validation_result: { final_strategy: string; invalid_reasons: string[] } } | null;
  source_failures: Array<{ failure_id: string; user_visible_message: string; impacted_plan_types: string[] }>;
  missing_components: string[];
  blocked_plan_types: string[];
  user_visible_warnings: string[];
};

export type RecalculateResponse = {
  schema_version: "1.15";
  plan: TravelPlan;
  change_summary: {
    cost_delta: { amount_minor: number; display_text: string };
    duration_delta_minutes: number;
    comfort_delta: number;
    message: string;
  };
};

export type DataSourceStatusResponse = {
  schema_version: "1.15";
  sources: Array<{ source_id: string; source_name: string; source_type: string; status: string; degraded: boolean; average_latency_ms: number | null }>;
};
