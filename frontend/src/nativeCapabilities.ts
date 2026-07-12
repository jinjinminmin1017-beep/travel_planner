import { Linking, PermissionsAndroid, Platform, Share } from "react-native";
import type { TravelPlan, TravelPlanResponse } from "./types";
import { formatMoney, minutesToText } from "./utils/format";

const RECENT_PLAN_KEY = "travel_planner_recent_plan_v1";
const RECENT_PLANS_KEY = "travel_planner_recent_plans_v2";
const FAVORITE_PLANS_KEY = "travel_planner_favorite_plans_v1";
const PLAN_REMINDERS_KEY = "travel_planner_plan_reminders_v1";
const RETENTION_PREFERENCES_KEY = "travel_planner_retention_preferences_v1";
const MAX_RECENT_PLANS = 5;

let memoryRecentPlan: RecentPlanSnapshot | null = null;
let memoryRecentPlans: RecentPlanSnapshot[] = [];
let memoryFavoritePlans: RecentPlanSnapshot[] = [];
let memoryPlanReminders: PlanReminder[] = [];
let memoryRetentionPreferences: RetentionPreferences = {
  destination_preferences_enabled: false,
  common_origin_enabled: false,
  common_origin_text: "",
  destination_preferences: [],
  updated_at: null
};

export type LocationPermissionResult = {
  status: "granted" | "denied" | "unavailable";
  userMessage: string;
};

export type RecentPlanSnapshot = {
  request_id: string;
  trace_id: string;
  correlation_id: string;
  plan_id: string;
  plan_name: string;
  plan_type: string;
  origin_text: string;
  destination_text: string;
  travel_date: string;
  total_duration_minutes: number;
  total_cost_text: string;
  generated_at: string;
  source_ids: string[];
  segment_count: number;
};

export type PlanReminderType = "TRIP" | "PRICE_STATUS";

export type PlanReminder = {
  reminder_id: string;
  request_id: string;
  trace_id: string;
  plan_id: string;
  plan_name: string;
  reminder_type: PlanReminderType;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  trigger_text: string;
};

export type RetentionPreferences = {
  destination_preferences_enabled: boolean;
  common_origin_enabled: boolean;
  common_origin_text: string;
  destination_preferences: string[];
  updated_at: string | null;
};

function webStorage() {
  return (globalThis as unknown as { localStorage?: Storage }).localStorage;
}

export async function requestLocationPermission(): Promise<LocationPermissionResult> {
  if (Platform.OS !== "android") {
    return {
      status: "unavailable",
      userMessage: "当前构建未接入系统定位模块，可继续手动输入出发地。"
    };
  }

  const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION, {
    title: "允许使用定位",
    message: "用于辅助填写出发地；拒绝后仍可手动输入。",
    buttonPositive: "允许",
    buttonNegative: "拒绝"
  });
  if (result === PermissionsAndroid.RESULTS.GRANTED) {
    return { status: "granted", userMessage: "已获得定位权限，请继续输入或确认出发地。" };
  }
  return { status: "denied", userMessage: "未获得定位权限，可继续手动输入出发地。" };
}

export async function openExternalUrl(url: string): Promise<{ opened: boolean; message?: string }> {
  try {
    const canOpen = await Linking.canOpenURL(url);
    if (!canOpen) return { opened: false, message: "系统没有可处理该链接的外部 App。" };
    await Linking.openURL(url);
    return { opened: true };
  } catch (error) {
    return { opened: false, message: error instanceof Error ? error.message : "外部跳转失败。" };
  }
}

export function buildItinerarySummary(plan: TravelPlan) {
  const segments = plan.segments.map((segment, index) => {
    if (segment.segment_type === "RAIL") return `${index + 1}. 高铁 ${segment.train_number}：${segment.origin_station} -> ${segment.destination_station}`;
    if (segment.segment_type === "FLIGHT") return `${index + 1}. 航班 ${segment.flight_number}：${segment.origin_airport} -> ${segment.destination_airport}`;
    return `${index + 1}. 接驳 ${segment.origin} -> ${segment.destination}，${minutesToText(segment.duration_minutes)}`;
  });
  return [
    plan.plan_name,
    `${formatMoney(plan.cost_breakdown.total_cost)} · ${minutesToText(plan.total_duration_minutes)}`,
    ...segments,
    "跳转后以外部官方平台展示为准；本 App 不代下单、不支付。"
  ].join("\n");
}

export async function sharePlan(plan: TravelPlan) {
  await Share.share({ message: buildItinerarySummary(plan) });
}

export async function copyPlanSummary(plan: TravelPlan): Promise<boolean> {
  const clipboard = (globalThis as unknown as { navigator?: { clipboard?: { writeText?: (value: string) => Promise<void> } } }).navigator?.clipboard;
  if (!clipboard?.writeText) return false;
  await clipboard.writeText(buildItinerarySummary(plan));
  return true;
}

export function saveRecentPlanSnapshot(response: TravelPlanResponse, plan: TravelPlan) {
  const snapshot: RecentPlanSnapshot = {
    request_id: response.request_id,
    trace_id: response.trace_id,
    correlation_id: response.correlation_id,
    plan_id: plan.plan_id,
    plan_name: plan.plan_name,
    plan_type: plan.plan_type,
    origin_text: response.travel_request.origin_text,
    destination_text: response.travel_request.destination_text,
    travel_date: response.travel_request.travel_date,
    total_duration_minutes: plan.total_duration_minutes,
    total_cost_text: formatMoney(plan.cost_breakdown.total_cost),
    generated_at: response.async_job?.updated_at.datetime ?? response.generated_at?.datetime ?? new Date().toISOString(),
    source_ids: plan.data_sources.map((source) => source.source_id),
    segment_count: plan.segments.length
  };
  memoryRecentPlan = snapshot;
  memoryRecentPlans = [snapshot, ...loadRecentPlanSnapshots().filter((item) => item.plan_id !== snapshot.plan_id)].slice(0, MAX_RECENT_PLANS);
  try {
    webStorage()?.setItem(RECENT_PLAN_KEY, JSON.stringify(snapshot));
    webStorage()?.setItem(RECENT_PLANS_KEY, JSON.stringify(memoryRecentPlans));
  } catch {
    // Memory fallback is enough when durable browser storage is unavailable.
  }
  return snapshot;
}

export function loadRecentPlanSnapshot(): RecentPlanSnapshot | null {
  try {
    const stored = webStorage()?.getItem(RECENT_PLAN_KEY);
    if (stored) return JSON.parse(stored) as RecentPlanSnapshot;
  } catch {
    return memoryRecentPlan;
  }
  return memoryRecentPlan;
}

export function loadRecentPlanSnapshots(): RecentPlanSnapshot[] {
  try {
    const stored = webStorage()?.getItem(RECENT_PLANS_KEY);
    if (stored) {
      memoryRecentPlans = JSON.parse(stored) as RecentPlanSnapshot[];
      return memoryRecentPlans;
    }
    const legacy = loadRecentPlanSnapshot();
    if (legacy) {
      memoryRecentPlans = [legacy];
      return memoryRecentPlans;
    }
  } catch {
    return memoryRecentPlans;
  }
  return memoryRecentPlans;
}

export function loadFavoritePlanSnapshots(): RecentPlanSnapshot[] {
  try {
    const stored = webStorage()?.getItem(FAVORITE_PLANS_KEY);
    if (stored) {
      memoryFavoritePlans = JSON.parse(stored) as RecentPlanSnapshot[];
      return memoryFavoritePlans;
    }
  } catch {
    return memoryFavoritePlans;
  }
  return memoryFavoritePlans;
}

export function isFavoritePlan(planId: string) {
  return loadFavoritePlanSnapshots().some((plan) => plan.plan_id === planId);
}

export function toggleFavoritePlanSnapshot(snapshot: RecentPlanSnapshot, enabled: boolean) {
  const current = loadFavoritePlanSnapshots().filter((plan) => plan.plan_id !== snapshot.plan_id);
  memoryFavoritePlans = enabled ? [snapshot, ...current] : current;
  try {
    webStorage()?.setItem(FAVORITE_PLANS_KEY, JSON.stringify(memoryFavoritePlans));
  } catch {
    // Keep the in-memory copy for platforms without durable storage.
  }
  return memoryFavoritePlans;
}

export function loadPlanReminders(): PlanReminder[] {
  try {
    const stored = webStorage()?.getItem(PLAN_REMINDERS_KEY);
    if (stored) {
      memoryPlanReminders = JSON.parse(stored) as PlanReminder[];
      return memoryPlanReminders;
    }
  } catch {
    return memoryPlanReminders;
  }
  return memoryPlanReminders;
}

export function isPlanReminderEnabled(planId: string, reminderType: PlanReminderType) {
  return loadPlanReminders().some((reminder) => reminder.plan_id === planId && reminder.reminder_type === reminderType && reminder.enabled);
}

export function setPlanReminder(snapshot: RecentPlanSnapshot, reminderType: PlanReminderType, enabled: boolean) {
  const now = new Date().toISOString();
  const triggerText = reminderType === "TRIP" ? `${snapshot.travel_date} 出行前提醒` : "价格或状态变化时提醒";
  const allReminders = loadPlanReminders();
  const existing = allReminders.find((reminder) => reminder.plan_id === snapshot.plan_id && reminder.reminder_type === reminderType);
  const current = allReminders.filter((reminder) => !(reminder.plan_id === snapshot.plan_id && reminder.reminder_type === reminderType));
  const next: PlanReminder = {
    reminder_id: `rem_${snapshot.plan_id}_${reminderType.toLowerCase()}`,
    request_id: snapshot.request_id,
    trace_id: snapshot.trace_id,
    plan_id: snapshot.plan_id,
    plan_name: snapshot.plan_name,
    reminder_type: reminderType,
    enabled,
    created_at: existing?.created_at ?? now,
    updated_at: now,
    trigger_text: triggerText
  };
  memoryPlanReminders = enabled ? [next, ...current] : current;
  try {
    webStorage()?.setItem(PLAN_REMINDERS_KEY, JSON.stringify(memoryPlanReminders));
  } catch {
    // Keep the in-memory copy for platforms without durable storage.
  }
  return memoryPlanReminders;
}

export function disablePlanReminder(planId: string, reminderType: PlanReminderType) {
  memoryPlanReminders = loadPlanReminders().filter((reminder) => !(reminder.plan_id === planId && reminder.reminder_type === reminderType));
  try {
    webStorage()?.setItem(PLAN_REMINDERS_KEY, JSON.stringify(memoryPlanReminders));
  } catch {
    // Keep the in-memory copy for platforms without durable storage.
  }
  return memoryPlanReminders;
}

export function loadRetentionPreferences(): RetentionPreferences {
  try {
    const stored = webStorage()?.getItem(RETENTION_PREFERENCES_KEY);
    if (stored) {
      memoryRetentionPreferences = JSON.parse(stored) as RetentionPreferences;
      return memoryRetentionPreferences;
    }
  } catch {
    return memoryRetentionPreferences;
  }
  return memoryRetentionPreferences;
}

export function saveRetentionPreferences(preferences: RetentionPreferences) {
  memoryRetentionPreferences = {
    ...preferences,
    common_origin_text: preferences.common_origin_enabled ? preferences.common_origin_text.trim() : "",
    destination_preferences: preferences.destination_preferences_enabled ? preferences.destination_preferences.map((item) => item.trim()).filter(Boolean).slice(0, 5) : [],
    updated_at: new Date().toISOString()
  };
  try {
    webStorage()?.setItem(RETENTION_PREFERENCES_KEY, JSON.stringify(memoryRetentionPreferences));
  } catch {
    // Keep the in-memory copy for platforms without durable storage.
  }
  return memoryRetentionPreferences;
}

export function hasExpiredRedirect(plan: TravelPlan, now = new Date()) {
  return plan.booking_redirects.some((redirect) => redirect.expires_at?.datetime && new Date(redirect.expires_at.datetime).getTime() <= now.getTime());
}
