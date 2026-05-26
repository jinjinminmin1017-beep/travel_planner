import type { BookingRedirect, DataSourceStatusResponse, ErrorResponse, RecalculateResponse, TravelPlanResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  const data = await response.json();
  if (!response.ok) {
    const error = data as ErrorResponse;
    throw new Error(error.user_visible_message || error.message || "Request failed");
  }
  return data as T;
}

export function planTrip(rawUserInput: string) {
  return request<TravelPlanResponse>("/api/travel/plan", {
    method: "POST",
    body: JSON.stringify({ raw_user_input: rawUserInput })
  });
}

export function loadDataSources() {
  return request<DataSourceStatusResponse>("/api/data-sources/status");
}

export function recalculate(planId: string, segmentId: string, changeType: "RAIL_SEAT" | "FLIGHT_CABIN" | "LOCAL_TRANSFER", optionId: string, optionValue: string) {
  return request<RecalculateResponse>("/api/travel/recalculate", {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.15",
      request_id: `req_ui_${Date.now()}`,
      idempotency_key: `idem_ui_${Date.now()}`,
      plan_id: planId,
      change_type: changeType,
      target_segment_id: segmentId,
      selected_option: {
        option_type: changeType,
        option_id: optionId,
        option_value: optionValue,
        source_option_version: "mock_v1"
      },
      recalculate_scope: "PLAN_TOTAL"
    })
  });
}

export function bookingRedirect(planId: string, segmentId: string | null, redirectType: string) {
  return request<{ redirect: BookingRedirect }>("/api/redirect/booking", {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.15",
      request_id: `req_redirect_${Date.now()}`,
      idempotency_key: `idem_redirect_${Date.now()}`,
      plan_id: planId,
      segment_id: segmentId,
      redirect_type: redirectType
    })
  });
}
