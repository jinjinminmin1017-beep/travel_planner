import type {
  IntercityTransportMode,
  Money,
  RecommendationSlot,
  RelaxationAlternative,
  Segment,
  TimePoint,
  TravelPlan,
  TravelPlanResponse,
  TravelRequest
} from "../types";

export type TimelinePoint = {
  segment: Segment;
  departureTime: TimePoint | null;
  arrivalTime: TimePoint | null;
  departureIsEstimated: boolean;
  arrivalIsEstimated: boolean;
};

export type PlanDifference = {
  comparedPlanId: string;
  costDeltaMinor: number;
  durationDeltaMinutes: number;
};

export type TransportModeAvailability = {
  mode: IntercityTransportMode;
  label: string;
  status: "AVAILABLE" | "EMPTY" | "UNAVAILABLE" | "EXCLUDED";
  statusLabel: string;
  reason: string;
  availablePlanCount: number;
  retryable: boolean;
};

const MODE_LABELS: Record<IntercityTransportMode, string> = { RAIL: "铁路", FLIGHT: "航班" };
const MODE_PLAN_TYPE_MARKERS: Record<IntercityTransportMode, string[]> = {
  RAIL: ["RAIL"],
  FLIGHT: ["FLIGHT", "MULTI_AIRPORT"]
};

export function planUsesTransportMode(plan: TravelPlan, mode: IntercityTransportMode) {
  return plan.segments.some((segment) => segment.segment_type === mode);
}

export function primaryPlanTransportMode(plan: TravelPlan): IntercityTransportMode | null {
  if (planUsesTransportMode(plan, "FLIGHT")) return "FLIGHT";
  if (planUsesTransportMode(plan, "RAIL")) return "RAIL";
  return null;
}

function planTypeMatchesMode(planType: string, mode: IntercityTransportMode) {
  return MODE_PLAN_TYPE_MARKERS[mode].some((marker) => planType.includes(marker));
}

function modeIsExcluded(response: TravelPlanResponse, mode: IntercityTransportMode) {
  const allowed = response.travel_request.hard_constraints.allowed_transport_modes;
  const excluded = response.travel_request.hard_constraints.excluded_transport_modes;
  if (excluded.includes(mode)) return true;
  return allowed.length > 0 && !allowed.includes(mode) && !allowed.includes("MIXED");
}

function modeIsNotApplicable(response: TravelPlanResponse, mode: IntercityTransportMode) {
  return response.missing_components.includes(mode === "FLIGHT" ? "flight_airport_candidates" : "rail_station_candidates");
}

export function deriveTransportModeAvailability(
  response: TravelPlanResponse,
  mode: IntercityTransportMode
): TransportModeAvailability {
  const availablePlanCount = response.plans.filter((plan) => planUsesTransportMode(plan, mode)).length;
  if (availablePlanCount > 0) {
    return {
      mode,
      label: MODE_LABELS[mode],
      status: "AVAILABLE",
      statusLabel: `${availablePlanCount} 个方案`,
      reason: `本次有 ${availablePlanCount} 个经过验证的${MODE_LABELS[mode]}方案。`,
      availablePlanCount,
      retryable: false
    };
  }
  if (modeIsExcluded(response, mode)) {
    return {
      mode,
      label: MODE_LABELS[mode],
      status: "EXCLUDED",
      statusLabel: "未纳入",
      reason: `你已将${MODE_LABELS[mode]}排除在本次规划之外。`,
      availablePlanCount: 0,
      retryable: false
    };
  }
  if (modeIsNotApplicable(response, mode)) {
    return {
      mode,
      label: MODE_LABELS[mode],
      status: "EXCLUDED",
      statusLabel: "路线不适用",
      reason: `本次路线没有可用于生成完整${MODE_LABELS[mode]}方案的交通节点。`,
      availablePlanCount: 0,
      retryable: false
    };
  }

  const failures = response.source_failures.filter((failure) =>
    failure.impacted_plan_types.some((planType) => planTypeMatchesMode(planType, mode))
  );
  const empty = failures.length > 0 && failures.every((failure) => failure.error_code?.endsWith("_EMPTY"));
  if (empty) {
    return {
      mode,
      label: MODE_LABELS[mode],
      status: "EMPTY",
      statusLabel: "未找到",
      reason: `${MODE_LABELS[mode]}数据源已完成查询，但未找到可验证方案。`,
      availablePlanCount: 0,
      retryable: false
    };
  }

  const explanation = (response.missing_plan_explanations ?? []).find((item) => planTypeMatchesMode(item.plan_type, mode));
  const reason = failures[0]?.user_visible_message || explanation?.user_visible_message || `本次暂时无法确认可用的${MODE_LABELS[mode]}方案。`;
  return {
    mode,
    label: MODE_LABELS[mode],
    status: "UNAVAILABLE",
    statusLabel: "暂不可用",
    reason,
    availablePlanCount: 0,
    retryable: failures.some((failure) => !failure.error_code?.endsWith("_EMPTY"))
  };
}

export function buildRouteTitle(request: Pick<TravelRequest, "origin_text" | "destination_text">) {
  const origin = request.origin_text.trim();
  const destination = request.destination_text.trim();
  if (origin && destination) return `${origin} → ${destination}`;
  if (origin) return `${origin}出发`;
  if (destination) return `前往${destination}`;
  return "路线待确认";
}

function hasUsableEndpoints(segment: Segment) {
  if (segment.segment_type === "RAIL") return Boolean(segment.origin_station && segment.destination_station);
  if (segment.segment_type === "FLIGHT") return Boolean(segment.origin_airport && segment.destination_airport);
  return Boolean(segment.origin && segment.destination);
}

export function countTransfers(segments: Segment[]) {
  const validSegmentCount = segments.filter((segment) => segment.duration_minutes >= 0 && hasUsableEndpoints(segment)).length;
  return Math.max(0, validSegmentCount - 1);
}

export function getPlanMetrics(plan: TravelPlan) {
  return {
    totalCost: plan.cost_breakdown.total_cost,
    totalDurationMinutes: plan.total_duration_minutes,
    transferCount: countTransfers(plan.segments)
  };
}

function addMinutes(time: TimePoint, minutes: number): TimePoint | null {
  const parsed = new Date(time.datetime);
  if (Number.isNaN(parsed.getTime())) return null;
  return {
    ...time,
    datetime: new Date(parsed.getTime() + minutes * 60_000).toISOString()
  };
}

export function buildRouteTimeline(plan: TravelPlan): TimelinePoint[] {
  let cursor = plan.departure_time ?? null;

  return plan.segments.map((segment) => {
    const explicitDeparture = segment.departure_time ?? null;
    const departureTime = explicitDeparture ?? cursor;
    const explicitArrival = segment.arrival_time ?? null;
    const arrivalTime = explicitArrival ?? (departureTime ? addMinutes(departureTime, segment.duration_minutes) : null);

    cursor = arrivalTime;
    return {
      segment,
      departureTime,
      arrivalTime,
      departureIsEstimated: !explicitDeparture && Boolean(departureTime),
      arrivalIsEstimated: !explicitArrival && Boolean(arrivalTime)
    };
  });
}

export function calculatePlanDifference(selectedPlan: TravelPlan, comparedPlan: TravelPlan): PlanDifference {
  return {
    comparedPlanId: comparedPlan.plan_id,
    costDeltaMinor: selectedPlan.cost_breakdown.total_cost.amount_minor - comparedPlan.cost_breakdown.total_cost.amount_minor,
    durationDeltaMinutes: selectedPlan.total_duration_minutes - comparedPlan.total_duration_minutes
  };
}

export function findRecommendationReason(selectedPlan: TravelPlan, recommendations: RecommendationSlot[]) {
  const matchingSlot = recommendations.find((slot) => slot.status === "AVAILABLE" && slot.plan_id === selectedPlan.plan_id);
  return matchingSlot?.reason.trim() || selectedPlan.comfort_score.explanation.trim() || null;
}

export function findCheapestPlan(plans: TravelPlan[]) {
  return plans.reduce<TravelPlan | null>((cheapest, plan) => {
    if (!cheapest) return plan;
    return plan.cost_breakdown.total_cost.amount_minor < cheapest.cost_breakdown.total_cost.amount_minor ? plan : cheapest;
  }, null);
}

export function findFastestPlan(plans: TravelPlan[]) {
  return plans.reduce<TravelPlan | null>((fastest, plan) => {
    if (!fastest) return plan;
    return plan.total_duration_minutes < fastest.total_duration_minutes ? plan : fastest;
  }, null);
}

export function moneyDelta(base: Money, amountMinor: number): Money {
  const absoluteAmount = Math.abs(amountMinor);
  const numericText = (absoluteAmount / 10 ** base.scale).toFixed(base.scale);
  return {
    amount_minor: absoluteAmount,
    currency: base.currency,
    scale: base.scale,
    display_text: base.currency === "CNY" ? `¥${numericText}` : null
  };
}

function asTimePoint(value: Record<string, unknown>): TimePoint | null {
  return typeof value.datetime === "string" && typeof value.timezone === "string"
    ? { datetime: value.datetime, timezone: value.timezone, source_timezone: typeof value.source_timezone === "string" ? value.source_timezone : value.timezone }
    : null;
}

function asMoney(value: Record<string, unknown>): Money | null {
  return typeof value.amount_minor === "number" && typeof value.currency === "string" && typeof value.scale === "number"
    ? { amount_minor: value.amount_minor, currency: value.currency, scale: value.scale, display_text: typeof value.display_text === "string" ? value.display_text : null }
    : null;
}

export function applyRelaxationToRequest(request: TravelRequest, alternative: RelaxationAlternative): TravelRequest {
  const next: TravelRequest = {
    ...request,
    schema_version: "1.17",
    request_id: `req_relax_${Date.now()}`,
    raw_user_input: `${request.raw_user_input}；已确认放宽：${alternative.violations.map((item) => item.user_visible_message).join("；")}`,
    hard_constraints: { ...request.hard_constraints }
  };
  for (const violation of alternative.violations) {
    const actualTime = asTimePoint(violation.actual_value);
    if (violation.constraint_type === "LATEST_ARRIVAL" && actualTime) {
      next.latest_arrival_time = actualTime;
      next.time_window_end = actualTime;
      next.hard_constraints.latest_arrival_time = actualTime;
    } else if (violation.constraint_type === "EARLIEST_DEPARTURE" && actualTime) {
      next.earliest_departure_time = actualTime;
      next.time_window_start = actualTime;
      next.hard_constraints.earliest_departure_time = actualTime;
    } else if (violation.constraint_type === "ARRIVAL_TIME_WINDOW" && actualTime) {
      next.time_window_start = null;
      next.time_window_end = actualTime;
      next.latest_arrival_time = actualTime;
      next.hard_constraints.latest_arrival_time = actualTime;
    } else if (violation.constraint_type === "DEPARTURE_TIME_WINDOW" && actualTime) {
      next.time_window_start = actualTime;
      next.time_window_end = null;
      next.earliest_departure_time = actualTime;
      next.hard_constraints.earliest_departure_time = actualTime;
    } else if (violation.constraint_type === "MAX_TOTAL_COST") {
      const actualMoney = asMoney(violation.actual_value);
      if (actualMoney) next.hard_constraints.max_total_cost = actualMoney;
    } else if (violation.constraint_type === "ALLOWED_TRANSPORT_MODES" && Array.isArray(violation.actual_value.modes)) {
      next.hard_constraints.allowed_transport_modes = violation.actual_value.modes.filter((item): item is string => typeof item === "string");
    } else if (violation.constraint_type === "EXCLUDED_TRANSPORT_MODES" && Array.isArray(violation.actual_value.modes)) {
      const actualModes = new Set(violation.actual_value.modes.filter((item): item is string => typeof item === "string"));
      next.hard_constraints.excluded_transport_modes = next.hard_constraints.excluded_transport_modes.filter((mode) => !actualModes.has(mode));
    } else if (violation.constraint_type === "PREFERRED_RAIL_SEAT" && typeof violation.actual_value.value === "string") {
      next.preferred_rail_seat = violation.actual_value.value;
    } else if (violation.constraint_type === "PREFERRED_FLIGHT_CABIN" && typeof violation.actual_value.value === "string") {
      next.preferred_flight_cabin = violation.actual_value.value;
    }
  }
  return next;
}
