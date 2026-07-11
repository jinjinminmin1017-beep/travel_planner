import type { Money, RecommendationSlot, Segment, TimePoint, TravelPlan, TravelRequest } from "../types";

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
  return {
    amount_minor: absoluteAmount,
    currency: base.currency,
    scale: base.scale,
    display_text: null
  };
}
