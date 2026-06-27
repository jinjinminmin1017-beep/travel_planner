import type { AppEventType, BookingRedirect, DataSourceStatusResponse, ErrorResponse, FeedbackCategory, FeedbackResponse, RecalculateChangeType, RecalculateResponse, RecalculateScope, TravelPlanResponse, TravelRequest } from "../types";
import { NativeModules, Platform } from "react-native";

const configuredApiBase = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();

function inferApiBaseFromDevServer() {
  const scriptURL = NativeModules.SourceCode?.scriptURL as string | undefined;
  const host = scriptURL?.match(/^https?:\/\/([^/:]+):\d+\//)?.[1];
  if (!host || host === "localhost" || host === "127.0.0.1") {
    return null;
  }
  return `http://${host}:8000`;
}

const LOCAL_EXPO_GO_API_BASE = "http://192.168.1.17:8000";
const DEFAULT_API_BASE = inferApiBaseFromDevServer() ?? LOCAL_EXPO_GO_API_BASE ?? (Platform.OS === "android" ? "http://10.0.2.2:8000" : "http://127.0.0.1:8000");
const API_BASE = configuredApiBase || DEFAULT_API_BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {})
      }
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Network request failed";
    throw new Error(`${message} (${API_BASE})`);
  }
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

export function planTripAsync(input: string | TravelRequest) {
  return request<TravelPlanResponse>("/api/travel/plan/async", {
    method: "POST",
    body: JSON.stringify(typeof input === "string" ? { raw_user_input: input } : { travel_request: input })
  });
}

export function pollPlanningJob(pollingUrl: string) {
  return request<TravelPlanResponse>(pollingUrl);
}

export function retryPlanningJob(jobId: string) {
  return request<TravelPlanResponse>(`/api/travel/jobs/${jobId}/retry`, {
    method: "POST"
  });
}

export function cancelPlanningJob(jobId: string) {
  return request<TravelPlanResponse>(`/api/travel/jobs/${jobId}/cancel`, {
    method: "POST"
  });
}

export function loadDataSources() {
  return request<DataSourceStatusResponse>("/api/data-sources/status");
}

const OPTION_TYPE_BY_CHANGE_TYPE: Record<RecalculateChangeType, "SEAT" | "CABIN" | "TRANSFER_MODE"> = {
  SEAT_TYPE: "SEAT",
  CABIN_TYPE: "CABIN",
  LOCAL_TRANSFER_MODE: "TRANSFER_MODE"
};

export function recalculate(planId: string, segmentId: string, changeType: RecalculateChangeType, optionId: string, optionValue: string, recalculateScope: RecalculateScope = "PLAN_AND_RECOMMENDATION") {
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
        option_type: OPTION_TYPE_BY_CHANGE_TYPE[changeType],
        option_id: optionId,
        option_value: optionValue,
        source_option_version: "ui_selected"
      },
      recalculate_scope: recalculateScope
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

export function submitFeedback(payload: {
  requestId: string;
  traceId: string;
  correlationId: string;
  planId: string;
  sourceId?: string | null;
  category: FeedbackCategory;
}) {
  return request<FeedbackResponse>("/api/feedback", {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.15",
      request_id: payload.requestId,
      trace_id: payload.traceId,
      correlation_id: payload.correlationId,
      plan_id: payload.planId,
      source_id: payload.sourceId ?? null,
      category: payload.category,
      message: null
    })
  });
}

export function trackEvent(payload: { eventType: AppEventType; requestId?: string | null; traceId?: string | null; planId?: string | null; metadata?: Record<string, unknown> }) {
  return request<{ accepted: boolean }>("/api/events", {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.15",
      event_type: payload.eventType,
      request_id: payload.requestId ?? null,
      trace_id: payload.traceId ?? null,
      plan_id: payload.planId ?? null,
      metadata: payload.metadata ?? {}
    })
  });
}
