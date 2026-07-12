import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Modal,
  type ImageSourcePropType,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View
} from "react-native";
import qingdaoHero from "../assets/destination-scenes/qingdao-pier.jpg";
import { cancelPlanningJob, planTripAsync, pollPlanningJob, retryPlanningJob, trackEvent } from "./api/client";
import { ui } from "./designSystem";
import { PlanningProgressScreen } from "./components/planning/PlanningProgressScreen";
import { ConstraintNoMatchScreen } from "./components/constraints/ConstraintNoMatchScreen";
import { ResultsBottomAction } from "./components/results/ResultsBottomAction";
import { ResultsOverview } from "./components/results/ResultsOverview";
import { RouteDetailScreen } from "./components/results/RouteDetailScreen";
import {
  hasExpiredRedirect,
  loadFavoritePlanSnapshots,
  loadRecentPlanSnapshots,
  loadRetentionPreferences,
  type RecentPlanSnapshot,
  requestLocationPermission,
  saveRecentPlanSnapshot,
  saveRetentionPreferences,
  toggleFavoritePlanSnapshot
} from "./nativeCapabilities";
import type { DataSourceMetadata, RecalculateResponse, RelaxationAlternative, SourceFailure, TimePoint, TravelPlan, TravelPlanResponse, TravelRequest } from "./types";
import { minutesToText } from "./utils/format";
import { applyRelaxationToRequest } from "./utils/routePlanning";

const HERO_IMAGES: Record<string, ImageSourcePropType> = {
  qingdao: qingdaoHero
};

type ActiveTab = "input" | "results";
type ResultsPane = "overview" | "details" | "sources";
type TimeAnchor = "DEPARTURE" | "ARRIVAL";

const POLL_INTERVAL_MS = 1200;
const MAX_POLL_ATTEMPTS = 100;
const ACTIVE_PLANNING_STATUSES = new Set(["PENDING", "RUNNING"]);
const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "RUNNING", "WAITING_SOURCE"]);
const HOUR_OPTIONS = Array.from({ length: 24 }, (_, index) => index);
const MINUTE_OPTIONS = Array.from({ length: 12 }, (_, index) => index * 5);
function findPlan(response: TravelPlanResponse | null, planId: string | null) {
  if (!response || !planId) return null;
  return response.plans.find((plan) => plan.plan_id === planId) ?? null;
}

function preferredRecommendationPlanId(response: TravelPlanResponse | null) {
  if (!response) return null;
  const recommendations = response.recommendation_result?.recommendations ?? [];
  const availableRecommendations = recommendations.filter((slot) => slot.status === "AVAILABLE" && slot.plan_id);
  const preferredType = response.travel_request.preferences.find((preference) => availableRecommendations.some((slot) => slot.recommendation_type === preference));
  return availableRecommendations.find((slot) => slot.recommendation_type === preferredType)?.plan_id ?? availableRecommendations[0]?.plan_id ?? null;
}

function planTypeLabel(type: string) {
  const labels: Record<string, string> = {
    DIRECT_RAIL: "高铁直达",
    TRANSFER_RAIL: "高铁中转",
    MULTI_TRANSFER_RAIL: "多段高铁",
    RAIL_TICKET_ENHANCEMENT: "票源增强",
    DIRECT_FLIGHT: "航班直飞",
    TRANSFER_FLIGHT: "航班中转",
    MULTI_AIRPORT_FLIGHT: "多机场组合",
    FLIGHT_RAIL_MIXED: "空铁混合",
    GROUND_ONLY: "地面交通",
    MIXED: "混合方案"
  };
  return labels[type] ?? type;
}

function formatClockTime(time?: TimePoint | null) {
  if (!time?.datetime) return null;
  const parsed = new Date(time.datetime);
  if (Number.isNaN(parsed.getTime())) return time.datetime;
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(parsed);
}

function clockInputValue(time?: TimePoint | null) {
  const formatted = formatClockTime(time);
  return formatted?.replace(/^24:/, "00:") ?? "";
}

function parseClockInput(value: string) {
  const match = value.trim().match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return { hour, minute };
}

function timePointForTravelDate(travelDate: string, value: string): TimePoint | null {
  const parsed = parseClockInput(value);
  if (!parsed) return null;
  const hour = String(parsed.hour).padStart(2, "0");
  const minute = String(parsed.minute).padStart(2, "0");
  return {
    datetime: `${travelDate}T${hour}:${minute}:00+08:00`,
    timezone: "Asia/Shanghai",
    source_timezone: "Asia/Shanghai"
  };
}

function clockPartsFromTime(time?: TimePoint | null) {
  return parseClockInput(clockInputValue(time)) ?? { hour: 9, minute: 0 };
}

function formatClockParts(hour: number, minute: number) {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function snapMinute(value: number) {
  return Math.max(0, Math.min(55, Math.round(value / 5) * 5));
}

function compactStatusLabel(value: string) {
  const labels: Record<string, string> = {
    AUTHORIZED: "已授权",
    NOT_AUTHORIZED: "未授权",
    ACTIVE: "可用",
    DISABLED: "禁用",
    TIMEOUT: "超时",
    UNAUTHORIZED: "未授权",
    PROVIDER_DOWN: "不可用",
    EMPTY_RESULT: "空结果",
    RATE_LIMITED: "限流"
  };
  return labels[value] ?? value;
}

function ScheduleAdjustPanel({
  response,
  plan,
  loading,
  onApply
}: {
  response: TravelPlanResponse;
  plan: TravelPlan | null;
  loading: boolean;
  onApply: (anchor: TimeAnchor, value: string) => void;
}) {
  const initialAnchor: TimeAnchor = response.travel_request.time_anchor_type === "ARRIVAL" ? "ARRIVAL" : "DEPARTURE";
  const initialTime = clockPartsFromTime(initialAnchor === "ARRIVAL" ? plan?.arrival_time ?? response.travel_request.latest_arrival_time : plan?.departure_time ?? response.travel_request.earliest_departure_time);
  const [anchor, setAnchor] = useState<TimeAnchor>(initialAnchor);
  const [selectedHour, setSelectedHour] = useState(initialTime.hour);
  const [selectedMinute, setSelectedMinute] = useState(snapMinute(initialTime.minute));
  const [timeModalOpen, setTimeModalOpen] = useState(false);
  const [draftHour, setDraftHour] = useState(initialTime.hour);
  const [draftMinute, setDraftMinute] = useState(snapMinute(initialTime.minute));

  useEffect(() => {
    const nextAnchor: TimeAnchor = response.travel_request.time_anchor_type === "ARRIVAL" ? "ARRIVAL" : "DEPARTURE";
    const nextTime = clockPartsFromTime(nextAnchor === "ARRIVAL" ? plan?.arrival_time ?? response.travel_request.latest_arrival_time : plan?.departure_time ?? response.travel_request.earliest_departure_time);
    setAnchor(nextAnchor);
    setSelectedHour(nextTime.hour);
    setSelectedMinute(snapMinute(nextTime.minute));
    setDraftHour(nextTime.hour);
    setDraftMinute(snapMinute(nextTime.minute));
  }, [response.request_id, plan?.plan_id]);

  function openTimeModal() {
    setDraftHour(selectedHour);
    setDraftMinute(selectedMinute);
    setTimeModalOpen(true);
  }

  function confirmTimeModal() {
    setSelectedHour(draftHour);
    setSelectedMinute(draftMinute);
    setTimeModalOpen(false);
  }

  function apply() {
    onApply(anchor, formatClockParts(selectedHour, selectedMinute));
  }

  return (
    <View style={styles.schedulePanel}>
      <View style={styles.scheduleHeader}>
        <Text style={styles.subheadingCompact}>时间</Text>
        <View style={styles.segmentedControl}>
          {(["DEPARTURE", "ARRIVAL"] as TimeAnchor[]).map((item) => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={item === "DEPARTURE" ? "按预估出发时间重新规划" : "按最晚到达时间重新规划"}
              accessibilityState={{ selected: anchor === item }}
              hitSlop={ui.hitSlop}
              key={item}
              style={[styles.segmentedButton, anchor === item && styles.segmentedButtonActive]}
              onPress={() => setAnchor(item)}
            >
              <Text style={[styles.segmentedButtonText, anchor === item && styles.segmentedButtonTextActive]}>{item === "DEPARTURE" ? "预估出发" : "最晚到达"}</Text>
            </Pressable>
          ))}
        </View>
      </View>
      <View style={styles.scheduleApplyRow}>
        <Pressable accessibilityRole="button" accessibilityLabel={`选择时间，当前为${formatClockParts(selectedHour, selectedMinute)}`} hitSlop={ui.hitSlop} style={styles.selectedTimeButton} onPress={openTimeModal}>
          <Text style={styles.selectedTimeText}>{formatClockParts(selectedHour, selectedMinute)}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="按当前时间重新规划" hitSlop={ui.hitSlop} style={styles.primarySmallButton} onPress={apply} disabled={loading}>
          <Text style={styles.primarySmallButtonText}>{loading ? "规划中" : "重新规划"}</Text>
        </Pressable>
      </View>
      <Modal animationType="fade" transparent visible={timeModalOpen} onRequestClose={() => setTimeModalOpen(false)}>
        <View style={styles.modalOverlay}>
          <Pressable style={styles.modalBackdrop} accessibilityRole="button" accessibilityLabel="关闭时间选择" onPress={() => setTimeModalOpen(false)} />
          <View style={styles.timeModalSheet}>
            <View style={styles.rowBetween}>
              <Text style={styles.subheadingCompact}>{anchor === "DEPARTURE" ? "选择预估出发" : "选择最晚到达"}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="关闭时间选择" hitSlop={ui.hitSlop} style={styles.modalCloseButton} onPress={() => setTimeModalOpen(false)}>
                <Text style={styles.iconButtonText}>关闭</Text>
              </Pressable>
            </View>
            <View style={styles.timeWheel}>
              <TimeWheelColumn
                label="小时"
                options={HOUR_OPTIONS}
                selectedValue={draftHour}
                onSelect={setDraftHour}
              />
              <Text style={styles.timeWheelSeparator}>:</Text>
              <TimeWheelColumn
                label="分钟"
                options={MINUTE_OPTIONS}
                selectedValue={draftMinute}
                onSelect={setDraftMinute}
              />
            </View>
            <View style={styles.scheduleApplyRow}>
              <Text style={styles.selectedTimeText}>{formatClockParts(draftHour, draftMinute)}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="确认选择时间" hitSlop={ui.hitSlop} style={styles.primarySmallButton} onPress={confirmTimeModal}>
                <Text style={styles.primarySmallButtonText}>确认</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function TimeWheelColumn({
  label,
  options,
  selectedValue,
  onSelect
}: {
  label: string;
  options: number[];
  selectedValue: number;
  onSelect: (value: number) => void;
}) {
  return (
    <View style={styles.timeWheelColumn}>
      <Text style={styles.timeWheelLabel}>{label}</Text>
      <ScrollView nestedScrollEnabled showsVerticalScrollIndicator={false} style={styles.timeWheelScroll} contentContainerStyle={styles.timeWheelContent}>
        {options.map((value) => {
          const selected = value === selectedValue;
          return (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`选择${label}${String(value).padStart(2, "0")}`}
              accessibilityState={{ selected }}
              hitSlop={ui.hitSlop}
              key={value}
              style={[styles.timeWheelOption, selected && styles.timeWheelOptionSelected]}
              onPress={() => onSelect(value)}
            >
              <Text style={[styles.timeWheelOptionText, selected && styles.timeWheelOptionTextSelected]}>{String(value).padStart(2, "0")}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

function ErrorState({ message, onRetry, onEdit }: { message: string; onRetry: () => void; onEdit: () => void }) {
  return (
    <View style={[styles.statePage, styles.errorStatePage]}>
      <Text style={styles.stateTitle}>规划失败</Text>
      <Text style={styles.bodyText}>{message || "这次没有拿到可用结果。"}</Text>
      <View style={styles.actionRow}>
        <Pressable accessibilityRole="button" accessibilityLabel="重试规划" hitSlop={ui.hitSlop} style={styles.primarySmallButton} onPress={onRetry}>
          <Text style={styles.primarySmallButtonText}>重试</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="改写出行需求" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={onEdit}>
          <Text style={styles.iconButtonText}>改写需求</Text>
        </Pressable>
      </View>
    </View>
  );
}

function EmptyResults({ response, onEdit }: { response: TravelPlanResponse | null; onEdit: () => void }) {
  return (
    <View style={styles.statePage}>
      <Text style={styles.stateTitle}>暂无可用方案</Text>
      <Text style={styles.bodyText}>
        {response?.missing_components.length ? `缺失：${response.missing_components.join("、")}` : "可以补充更明确的出发地、目的地、日期或放宽交通偏好。"}
      </Text>
      {response?.source_failures.slice(0, 2).map((failure) => (
        <Text style={styles.secondaryText} key={failure.failure_id}>{failure.user_visible_message}</Text>
      ))}
      <Pressable accessibilityRole="button" accessibilityLabel="重新输入出行需求" hitSlop={ui.hitSlop} style={styles.primarySmallButton} onPress={onEdit}>
        <Text style={styles.primarySmallButtonText}>重新输入</Text>
      </Pressable>
    </View>
  );
}

function SourceFailureRow({ failure }: { failure: SourceFailure }) {
  return (
    <View style={styles.sourceFailureCard}>
      <View style={styles.rowBetween}>
        <Text style={styles.optionTitle}>{failure.source_id}</Text>
        <Text style={styles.statusPill}>{compactStatusLabel(failure.failure_class)}</Text>
      </View>
      <Text style={styles.secondaryText}>{failure.user_visible_message}</Text>
      <Text style={styles.secondaryText}>处理：{failure.final_handling_strategy}</Text>
    </View>
  );
}

function DataSourceRow({ source }: { source: DataSourceMetadata }) {
  return (
    <View style={styles.sourceCard}>
      <View style={styles.rowBetween}>
        <View style={styles.flex}>
          <Text style={styles.optionTitle}>{source.source_name}</Text>
          <Text style={styles.secondaryText}>{source.source_id} · {source.source_type}</Text>
        </View>
        <Text style={styles.statusPill}>{compactStatusLabel(source.license_status)}</Text>
      </View>
      <Text style={styles.secondaryText}>
        {source.authority_level} · {source.commercial_allowed ? "商业可用" : "非商业或未授权"} · {source.cacheable ? "可缓存" : "不可缓存"}
      </Text>
    </View>
  );
}

function DataSourcesPage({ response, plan, onBack }: { response: TravelPlanResponse; plan: TravelPlan | null; onBack: () => void }) {
  const sources = plan?.data_sources.length ? plan.data_sources : [];
  return (
    <View>
      <View style={styles.rowBetween}>
        <View style={styles.flex}>
          <Text style={styles.kicker}>request_id</Text>
          <Text style={styles.requestIdText}>{response.request_id}</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="返回方案总览" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={onBack}>
          <Text style={styles.iconButtonText}>返回</Text>
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>数据来源</Text>
      {sources.length ? sources.map((source) => <DataSourceRow key={`${source.source_id}-${source.fetched_at.datetime}`} source={source} />) : (
        <View style={styles.card}>
          <Text style={styles.bodyText}>当前方案没有可展示的数据来源。</Text>
        </View>
      )}

      <Text style={styles.subheading}>缺失与降级</Text>
      {response.missing_components.length > 0 && <Text style={styles.bodyText}>缺失：{response.missing_components.join("、")}</Text>}
      {response.source_failures.length ? response.source_failures.map((failure) => <SourceFailureRow key={failure.failure_id} failure={failure} />) : (
        <Text style={styles.secondaryText}>没有记录到数据源失败。</Text>
      )}
    </View>
  );
}

function RetentionPlanList({
  title,
  plans,
  emptyText,
  onOpen
}: {
  title: string;
  plans: RecentPlanSnapshot[];
  emptyText: string;
  onOpen: (plan: RecentPlanSnapshot) => void;
}) {
  return (
    <View style={styles.retentionPanel}>
      <Text style={styles.subheadingCompact}>{title}</Text>
      {plans.length === 0 ? (
        <Text style={styles.secondaryText}>{emptyText}</Text>
      ) : (
        plans.slice(0, 3).map((plan) => (
          <Pressable accessibilityRole="button" accessibilityLabel={`查看${title}：${plan.plan_name}`} hitSlop={ui.hitSlop} style={styles.retentionRow} key={`${title}-${plan.plan_id}`} onPress={() => onOpen(plan)}>
            <View style={styles.flex}>
              <Text style={styles.optionTitle}>{plan.origin_text} 到 {plan.destination_text}</Text>
              <Text style={styles.secondaryText}>
                {plan.total_cost_text} · {minutesToText(plan.total_duration_minutes)} · {plan.travel_date}
              </Text>
            </View>
            <Text style={styles.statusPill}>{planTypeLabel(plan.plan_type)}</Text>
          </Pressable>
        ))
      )}
    </View>
  );
}

export default function App() {
  const { width } = useWindowDimensions();
  const wideLayout = width >= ui.contentMaxWidth;
  const planningRunId = useRef(0);
  const [rawInput, setRawInput] = useState("");
  const [response, setResponse] = useState<TravelPlanResponse | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<ActiveTab>("input");
  const [resultsPane, setResultsPane] = useState<ResultsPane>("overview");
  const [scheduleExpanded, setScheduleExpanded] = useState(false);
  const [recentPlans, setRecentPlans] = useState<RecentPlanSnapshot[]>(() => loadRecentPlanSnapshots());
  const [favoritePlans, setFavoritePlans] = useState<RecentPlanSnapshot[]>(() => loadFavoritePlanSnapshots());
  const [retentionPreferences, setRetentionPreferences] = useState(() => loadRetentionPreferences());
  const [commonOriginDraft, setCommonOriginDraft] = useState(() => loadRetentionPreferences().common_origin_text);
  const [destinationPreferenceDraft, setDestinationPreferenceDraft] = useState(() => loadRetentionPreferences().destination_preferences.join("、"));

  const recommendations = response?.recommendation_result?.recommendations ?? [];
  const selectedPlan = useMemo(() => {
    const explicit = findPlan(response, selectedPlanId);
    if (explicit) return explicit;
    return findPlan(response, preferredRecommendationPlanId(response)) ?? response?.plans[0] ?? null;
  }, [response, selectedPlanId]);
  const recommendedPlanIds = useMemo(() => new Set(recommendations.map((slot) => slot.plan_id).filter(Boolean)), [recommendations]);
  const candidatePlans = useMemo(() => response?.plans.filter((plan) => !recommendedPlanIds.has(plan.plan_id)) ?? [], [response, recommendedPlanIds]);
  const selectedPlanFavorite = selectedPlan ? favoritePlans.some((plan) => plan.plan_id === selectedPlan.plan_id) : false;
  const recentPlan = recentPlans[0] ?? null;

  useEffect(() => {
    if (response && selectedPlan) {
      saveRecentPlanSnapshot(response, selectedPlan);
      setRecentPlans(loadRecentPlanSnapshots());
    }
  }, [response, selectedPlan]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state !== "active" || !response) return;
      if (isPlanningActive(response)) {
        const runId = planningRunId.current;
        void pollUntilSettled(response, runId).finally(() => setLoading(false));
      } else if (selectedPlan && hasExpiredRedirect(selectedPlan)) {
        Alert.alert("跳转信息可能已过期", "请重新打开跳转入口，系统会生成新的 redirect-only 链接。");
      }
    });
    return () => subscription.remove();
  }, [response, selectedPlan]);

  function isPlanningActive(nextResponse: TravelPlanResponse) {
    const planningActive = ACTIVE_PLANNING_STATUSES.has(nextResponse.planning_status);
    const jobActive = nextResponse.async_job ? ACTIVE_JOB_STATUSES.has(nextResponse.async_job.job_status) : false;
    return planningActive || jobActive;
  }

  function syncSelection(nextResponse: TravelPlanResponse) {
    if (nextResponse.plans.length === 0) {
      setSelectedPlanId(null);
      return;
    }
    setSelectedPlanId((current) => findPlan(nextResponse, current)?.plan_id ?? preferredRecommendationPlanId(nextResponse) ?? nextResponse.plans[0]?.plan_id ?? null);
  }

  async function pollUntilSettled(initialResponse: TravelPlanResponse, runId: number, preserveCurrentResults = false) {
    let current = initialResponse;
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      if (runId !== planningRunId.current) return;
      if (!current.async_job?.polling_url || !isPlanningActive(current)) return;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      if (runId !== planningRunId.current) return;
      current = await pollPlanningJob(current.async_job.polling_url);
      if (!preserveCurrentResults || current.plans.length > 0 || current.planning_status === "NO_MATCH") {
        setResponse(current);
        syncSelection(current);
      }
      if (!isPlanningActive(current)) {
        if (current.planning_status !== "FAILED") {
          const eventType = current.planning_status === "NO_MATCH" ? "PLANNING_NO_MATCH" : current.planning_status === "PARTIAL" ? "PLANNING_PARTIAL" : "PLANNING_SUCCESS";
          void trackEvent({
            eventType,
            requestId: current.request_id,
            traceId: current.trace_id,
            planId: current.plans[0]?.plan_id ?? null,
            metadata: current.planning_status === "NO_MATCH"
              ? {
                  planning_status: current.planning_status,
                  constraint_types: current.constraint_analysis?.alternatives.flatMap((item) => item.violations.map((violation) => violation.constraint_type)) ?? [],
                  alternative_count: current.constraint_analysis?.alternatives.length ?? 0,
                  coverage_statuses: current.constraint_analysis?.coverage.map((item) => item.status) ?? []
                }
              : { planning_status: current.planning_status }
          }).catch(() => undefined);
        }
        return;
      }
    }
    setError("规划仍在进行中，请稍后重试或改写需求。");
  }

  async function startPlanning(input: string | TravelRequest, metadata: Record<string, unknown> = {}, preserveCurrentResults = false) {
    setLoading(true);
    setError("");
    if (!preserveCurrentResults) setResponse(null);
    setResultsPane("overview");
    setActiveTab("results");
    const runId = planningRunId.current + 1;
    planningRunId.current = runId;
    try {
      void trackEvent({ eventType: "INPUT_SUBMITTED", metadata }).catch(() => undefined);
      const result = await planTripAsync(input);
      if (!preserveCurrentResults || result.plans.length > 0 || result.planning_status === "NO_MATCH") {
        setResponse(result);
        syncSelection(result);
      }
      await pollUntilSettled(result, runId, preserveCurrentResults);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  async function submit() {
    const trimmedInput = rawInput.trim();
    if (!trimmedInput) {
      setError("请先写下出发地、目的地和出行时间。");
      setActiveTab("input");
      return;
    }
    await startPlanning(trimmedInput, { input_length: trimmedInput.length });
  }

  async function replanWithTime(anchor: TimeAnchor, value: string) {
    if (!response) return;
    const point = timePointForTravelDate(response.travel_request.travel_date, value);
    if (!point) {
      Alert.alert("时间格式不对", "请按 HH:mm 输入，例如 09:30。");
      return;
    }
    const request: TravelRequest = {
      ...response.travel_request,
      request_id: `req_ui_time_${Date.now()}`,
      raw_user_input: `${response.travel_request.raw_user_input}；${anchor === "DEPARTURE" ? "调整最早出发" : "调整最晚到达"} ${value}`,
      time_anchor_type: anchor,
      time_window_start: anchor === "DEPARTURE" ? point : null,
      time_window_end: anchor === "ARRIVAL" ? point : null,
      earliest_departure_time: anchor === "DEPARTURE" ? point : null,
      latest_arrival_time: anchor === "ARRIVAL" ? point : null,
      hard_constraints: {
        ...response.travel_request.hard_constraints,
        earliest_departure_time: anchor === "DEPARTURE" ? point : null,
        latest_arrival_time: anchor === "ARRIVAL" ? point : null
      }
    };
    await startPlanning(request, { source: "time_adjustment", time_anchor_type: anchor, time_value: value }, true);
  }

  async function confirmRelaxation(alternative: RelaxationAlternative) {
    if (!response) return;
    const request = applyRelaxationToRequest(response.travel_request, alternative);
    await startPlanning(request, {
      source: "constraint_relaxation",
      alternative_category: alternative.category,
      constraint_types: alternative.violations.map((item) => item.constraint_type)
    });
  }

  async function requestLocation() {
    const result = await requestLocationPermission();
    Alert.alert(result.status === "granted" ? "定位权限已开启" : "继续手动输入", result.userMessage);
  }

  function snapshotFor(plan: TravelPlan) {
    if (!response) return null;
    const snapshot = saveRecentPlanSnapshot(response, plan);
    setRecentPlans(loadRecentPlanSnapshots());
    return snapshot;
  }

  function toggleFavorite(plan: TravelPlan) {
    const snapshot = snapshotFor(plan);
    if (!snapshot) return;
    const enabled = !favoritePlans.some((item) => item.plan_id === plan.plan_id);
    const nextFavorites = toggleFavoritePlanSnapshot(snapshot, enabled);
    setFavoritePlans(nextFavorites);
    void trackEvent({
      eventType: "FAVORITE_TOGGLED",
      requestId: snapshot.request_id,
      traceId: snapshot.trace_id,
      planId: snapshot.plan_id,
      metadata: { enabled }
    }).catch(() => undefined);
    Alert.alert(enabled ? "已收藏" : "已取消收藏", enabled ? "收藏只保存脱敏方案摘要。" : "该方案已从收藏中移除。");
  }

  function openStoredPlan(snapshot: RecentPlanSnapshot) {
    void trackEvent({
      eventType: "RECENT_PLAN_VIEWED",
      requestId: snapshot.request_id,
      traceId: snapshot.trace_id,
      planId: snapshot.plan_id,
      metadata: { source: "retention_panel" }
    }).catch(() => undefined);
    Alert.alert(
      snapshot.plan_name,
      `${snapshot.origin_text} 到 ${snapshot.destination_text}\n${snapshot.total_cost_text} · ${minutesToText(snapshot.total_duration_minutes)}\n这是脱敏历史摘要；如需最新价格或状态，请重新规划或跳转确认。`
    );
  }

  function savePreferenceSettings(nextEnabled: Partial<{ common_origin_enabled: boolean; destination_preferences_enabled: boolean }>) {
    const updated = saveRetentionPreferences({
      ...retentionPreferences,
      ...nextEnabled,
      common_origin_text: commonOriginDraft,
      destination_preferences: destinationPreferenceDraft.split(/[、,，]/).map((item) => item.trim()).filter(Boolean)
    });
    setRetentionPreferences(updated);
    setCommonOriginDraft(updated.common_origin_text);
    setDestinationPreferenceDraft(updated.destination_preferences.join("、"));
    void trackEvent({
      eventType: "PREFERENCE_UPDATED",
      metadata: {
        common_origin_enabled: updated.common_origin_enabled,
        destination_preferences_enabled: updated.destination_preferences_enabled,
        destination_count: updated.destination_preferences.length
      }
    }).catch(() => undefined);
    Alert.alert("偏好已更新", "偏好可随时关闭；关闭后对应内容会从本地设置中清空。");
  }

  async function retrySources() {
    const jobId = response?.async_job?.job_id;
    if (!jobId) return;
    setLoading(true);
    setError("");
    setResultsPane("overview");
    try {
      const runId = planningRunId.current + 1;
      planningRunId.current = runId;
      const result = await retryPlanningJob(jobId);
      if (result.plans.length > 0) {
        setResponse(result);
        syncSelection(result);
      }
      await pollUntilSettled(result, runId, true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重试失败");
    } finally {
      setLoading(false);
    }
  }

  async function cancelCurrentJob() {
    const jobId = response?.async_job?.job_id;
    if (!jobId) return;
    planningRunId.current += 1;
    setLoading(false);
    try {
      const cancelled = await cancelPlanningJob(jobId);
      setResponse(cancelled);
      syncSelection(cancelled);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "取消失败");
    }
  }

  function replacePlan(updatedResponse: RecalculateResponse) {
    setResponse((current) => {
      if (!current) return current;
      return {
        ...current,
        recommendation_result: updatedResponse.recommendation_result ?? current.recommendation_result,
        plans: current.plans.map((plan) => (plan.plan_id === updatedResponse.plan.plan_id ? updatedResponse.plan : plan))
      };
    });
    setSelectedPlanId(updatedResponse.plan.plan_id);
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.appShell}>
        {activeTab === "input" ? (
          <ScrollView style={styles.screen} contentContainerStyle={[styles.content, styles.inputContent, wideLayout && styles.contentWide]} keyboardShouldPersistTaps="handled">
            <View style={styles.topbar}>
              <Text style={styles.appTitle}>出行搭子</Text>
              <Text style={styles.appSubtitle}>一念云起，把出行需求说给搭子听。</Text>
            </View>

            <View style={styles.promptStage}>
              <View style={styles.promptPanel}>
                <Text style={styles.promptLabel}>你想怎么走？</Text>
                <TextInput
                  style={styles.input}
                  value={rawInput}
                  onChangeText={setRawInput}
                  multiline
                  placeholder="说说你从哪里出发、到哪里、什么时候走。"
                  textAlignVertical="top"
                />
                <View style={styles.inputActions}>
                  <Pressable accessibilityRole="button" accessibilityLabel="请求系统定位权限" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={requestLocation}>
                    <Text style={styles.iconButtonText}>使用定位</Text>
                  </Pressable>
                  {recentPlan && (
                    <View style={styles.recentPlanPill}>
                      <Text style={styles.kicker}>最近方案</Text>
                      <Text style={styles.secondaryText}>{recentPlan.total_cost_text} · {minutesToText(recentPlan.total_duration_minutes)}</Text>
                    </View>
                  )}
                </View>
                <Pressable accessibilityRole="button" accessibilityLabel="开始规划出行方案" hitSlop={ui.hitSlop} style={[styles.submitButton, loading && styles.submitButtonDisabled]} onPress={submit} disabled={loading}>
                  {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.submitButtonText}>开始规划</Text>}
                </Pressable>
              </View>
              <RetentionPlanList title="最近规划" plans={recentPlans} emptyText="完成一次规划后，会在这里保存脱敏摘要。" onOpen={openStoredPlan} />
              <RetentionPlanList title="收藏方案" plans={favoritePlans} emptyText="在方案详情里点收藏，之后会显示在这里。" onOpen={openStoredPlan} />
              <View style={styles.retentionPanel}>
                <Text style={styles.subheadingCompact}>偏好记忆</Text>
                <Text style={styles.secondaryText}>只有你开启后才会保存常用出发地和目的地偏好；关闭会清空对应内容。</Text>
                <TextInput
                  style={styles.compactInput}
                  value={commonOriginDraft}
                  onChangeText={setCommonOriginDraft}
                  placeholder="常用出发地，例如 上海虹桥"
                />
                <View style={styles.actionRowWrap}>
                  <Pressable accessibilityRole="switch" accessibilityLabel="常用出发地记忆开关" accessibilityState={{ checked: retentionPreferences.common_origin_enabled }} hitSlop={ui.hitSlop} style={[styles.feedbackButton, retentionPreferences.common_origin_enabled && styles.toggleButtonActive]} onPress={() => savePreferenceSettings({ common_origin_enabled: !retentionPreferences.common_origin_enabled })}>
                    <Text style={styles.iconButtonText}>{retentionPreferences.common_origin_enabled ? "关闭出发地" : "记住出发地"}</Text>
                  </Pressable>
                  {retentionPreferences.common_origin_enabled && retentionPreferences.common_origin_text ? (
                    <Pressable accessibilityRole="button" accessibilityLabel="套用常用出发地" hitSlop={ui.hitSlop} style={styles.feedbackButton} onPress={() => setRawInput((current) => (current ? `${retentionPreferences.common_origin_text} 出发，${current}` : `从${retentionPreferences.common_origin_text}出发，`))}>
                      <Text style={styles.iconButtonText}>套用</Text>
                    </Pressable>
                  ) : null}
                </View>
                <TextInput
                  style={styles.compactInput}
                  value={destinationPreferenceDraft}
                  onChangeText={setDestinationPreferenceDraft}
                  placeholder="目的地偏好，用顿号或逗号分隔"
                />
                <Pressable accessibilityRole="switch" accessibilityLabel="目的地偏好记忆开关" accessibilityState={{ checked: retentionPreferences.destination_preferences_enabled }} hitSlop={ui.hitSlop} style={[styles.feedbackButton, retentionPreferences.destination_preferences_enabled && styles.toggleButtonActive]} onPress={() => savePreferenceSettings({ destination_preferences_enabled: !retentionPreferences.destination_preferences_enabled })}>
                  <Text style={styles.iconButtonText}>{retentionPreferences.destination_preferences_enabled ? "关闭目的地偏好" : "记住目的地偏好"}</Text>
                </Pressable>
                <Pressable accessibilityRole="button" accessibilityLabel="保存当前偏好设置" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={() => savePreferenceSettings({})}>
                  <Text style={styles.iconButtonText}>保存偏好</Text>
                </Pressable>
              </View>
              {error ? <Text style={styles.errorPanel}>{error}</Text> : null}
            </View>
          </ScrollView>
        ) : (
          <ScrollView style={styles.screen} contentContainerStyle={[styles.content, wideLayout && styles.contentWide]}>
            {loading && (!response || response.plans.length === 0) ? (
              <PlanningProgressScreen
                destinationText={response?.travel_request.destination_text}
                onCancel={response?.async_job ? cancelCurrentJob : undefined}
                originText={response?.travel_request.origin_text}
                progress={response?.progress ?? 0}
                statusText={response?.async_job?.job_status === "WAITING_SOURCE" ? "正在等待外部数据来源返回" : undefined}
              />
            ) : error && !response ? (
              <ErrorState message={error} onRetry={submit} onEdit={() => setActiveTab("input")} />
            ) : !response ? (
              <View style={styles.emptyState}>
                <Text style={styles.emptyTitle}>还没有规划结果</Text>
                <Text style={styles.secondaryText}>先到云起写下出发地、目的地和时间，提交后会自动切到这里。</Text>
                <Pressable accessibilityRole="button" accessibilityLabel="前往云起输入页" hitSlop={ui.hitSlop} style={styles.emptyButton} onPress={() => setActiveTab("input")}>
                  <Text style={styles.iconButtonText}>去云起</Text>
                </Pressable>
              </View>
            ) : response.planning_status === "NO_MATCH" && response.constraint_analysis ? (
              <ConstraintNoMatchScreen
                busy={loading}
                onConfirm={confirmRelaxation}
                onEdit={() => setActiveTab("input")}
                response={response}
              />
            ) : response.plans.length === 0 ? (
              <EmptyResults response={response} onEdit={() => setActiveTab("input")} />
            ) : resultsPane === "sources" ? (
              <DataSourcesPage response={response} plan={selectedPlan} onBack={() => setResultsPane("overview")} />
            ) : resultsPane === "details" && selectedPlan ? (
              <RouteDetailScreen
                favorite={selectedPlanFavorite}
                onBack={() => setResultsPane("overview")}
                onFavoriteToggle={toggleFavorite}
                onRecalculated={replacePlan}
                onSources={() => setResultsPane("sources")}
                plan={selectedPlan}
                response={response}
              />
            ) : selectedPlan ? (
              <>
                {error ? <Text style={styles.errorPanel}>{error}</Text> : null}
                <ResultsOverview
                  busy={loading}
                  candidatePlans={candidatePlans}
                  imageSource={HERO_IMAGES[response.destination_presentation?.destination_key ?? "generic"]}
                  onRetrySources={retrySources}
                  onSelectCandidate={(plan) => setSelectedPlanId(plan.plan_id)}
                  onSelectRecommendation={(plan, slot) => {
                    setSelectedPlanId(plan.plan_id);
                    void trackEvent({ eventType: "RECOMMENDATION_CLICK", requestId: response.request_id, traceId: response.trace_id, planId: plan.plan_id, metadata: { recommendation_type: slot.recommendation_type } }).catch(() => undefined);
                  }}
                  onSources={() => setResultsPane("sources")}
                  plan={selectedPlan}
                  recommendations={recommendations}
                  response={response}
                  schedulePanel={
                    <View>
                      <Pressable accessibilityRole="button" accessibilityLabel={`${scheduleExpanded ? "收起" : "展开"}时间调整`} accessibilityState={{ expanded: scheduleExpanded }} hitSlop={ui.hitSlop} onPress={() => setScheduleExpanded((current) => !current)} style={styles.scheduleToggle}>
                        <Text style={styles.scheduleToggleText}>{scheduleExpanded ? "收起时间调整" : "调整时间"}</Text>
                      </Pressable>
                      {scheduleExpanded ? <ScheduleAdjustPanel response={response} plan={selectedPlan} loading={loading} onApply={replanWithTime} /> : null}
                    </View>
                  }
                />
              </>
            ) : <EmptyResults response={response} onEdit={() => setActiveTab("input")} />}
          </ScrollView>
        )}

        {activeTab === "results" && resultsPane === "overview" && selectedPlan && response?.plans.length ? (
          <ResultsBottomAction disabled={loading} favorite={selectedPlanFavorite} onDetails={() => setResultsPane("details")} onFavorite={() => toggleFavorite(selectedPlan)} />
        ) : null}

        <View style={styles.bottomTabs}>
          <Pressable
            accessibilityRole="tab"
            accessibilityLabel="云起，输入出行需求"
            accessibilityState={{ selected: activeTab === "input" }}
            hitSlop={ui.hitSlop}
            style={[styles.tabButton, activeTab === "input" && styles.tabButtonActive]}
            onPress={() => setActiveTab("input")}
          >
            <Text style={[styles.tabLabel, activeTab === "input" && styles.tabTextActive]}>云起</Text>
          </Pressable>
          <Pressable
            accessibilityRole="tab"
            accessibilityLabel="路明，查看规划结果"
            accessibilityState={{ selected: activeTab === "results" }}
            hitSlop={ui.hitSlop}
            style={[styles.tabButton, activeTab === "results" && styles.tabButtonActive]}
            onPress={() => setActiveTab("results")}
          >
            <Text style={[styles.tabLabel, activeTab === "results" && styles.tabTextActive]}>路明</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: ui.colors.background
  },
  appShell: {
    flex: 1
  },
  screen: {
    flex: 1
  },
  content: {
    padding: 16,
    paddingBottom: 24
  },
  contentWide: {
    alignSelf: "center",
    maxWidth: ui.contentMaxWidth,
    width: "100%"
  },
  scheduleToggle: {
    alignItems: "center",
    alignSelf: "flex-start",
    justifyContent: "center",
    minHeight: ui.touchTarget,
    paddingHorizontal: ui.spacing.sm
  },
  scheduleToggleText: {
    color: ui.colors.primary,
    fontSize: 13,
    fontWeight: "800"
  },
  inputContent: {
    flexGrow: 1
  },
  topbar: {
    marginBottom: 12
  },
  appTitle: {
    color: "#172126",
    fontSize: 28,
    fontWeight: "800"
  },
  appSubtitle: {
    color: "#66747c",
    fontSize: 13,
    marginTop: 2
  },
  hero: {
    minHeight: 164,
    borderRadius: 8,
    overflow: "hidden",
    marginBottom: 14
  },
  heroImage: {
    borderRadius: 8
  },
  heroFallback: {
    backgroundColor: "#234f5f"
  },
  heroShade: {
    flex: 1,
    justifyContent: "flex-end",
    padding: 18,
    backgroundColor: "rgba(10, 25, 31, 0.42)"
  },
  heroKicker: {
    color: "#d7f0ef",
    fontSize: 12,
    fontWeight: "700"
  },
  heroTitle: {
    color: "#ffffff",
    fontSize: 28,
    fontWeight: "800",
    marginTop: 4
  },
  heroMeta: {
    color: "#f1f6f7",
    fontSize: 13,
    marginTop: 8
  },
  queryPanel: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    padding: 12,
    gap: 10,
    marginBottom: 16
  },
  promptStage: {
    flex: 1,
    justifyContent: "flex-end",
    minHeight: 520
  },
  promptPanel: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    gap: 10,
    padding: 12
  },
  inputActions: {
    alignItems: "center",
    flexDirection: "row",
    gap: 10
  },
  recentPlanPill: {
    backgroundColor: "#f2f6f7",
    borderRadius: 8,
    flex: 1,
    justifyContent: "center",
    minHeight: ui.touchTarget,
    paddingHorizontal: 10,
    paddingVertical: 7
  },
  promptLabel: {
    color: "#126b75",
    fontSize: 13,
    fontWeight: "800"
  },
  input: {
    minHeight: 112,
    color: "#172126",
    fontSize: 16,
    lineHeight: 23
  },
  compactInput: {
    backgroundColor: "#ffffff",
    borderColor: "#dce4e6",
    borderRadius: 8,
    borderWidth: 1,
    color: "#172126",
    fontSize: 14,
    minHeight: ui.touchTarget,
    paddingHorizontal: 10,
    paddingVertical: 9
  },
  submitButton: {
    alignItems: "center",
    backgroundColor: "#126b75",
    borderRadius: 8,
    minHeight: 48,
    justifyContent: "center"
  },
  submitButtonDisabled: {
    opacity: 0.72
  },
  submitButtonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "800"
  },
  errorPanel: {
    backgroundColor: "#fff0ed",
    borderRadius: 8,
    color: "#9d2f21",
    marginBottom: 12,
    padding: 12
  },
  sectionHeader: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 2
  },
  sectionTitle: {
    color: "#172126",
    fontSize: 20,
    fontWeight: "800"
  },
  horizontalList: {
    gap: 10,
    paddingVertical: 10
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    padding: 14
  },
  recommendationCard: {
    minHeight: 154,
    width: 244
  },
  cardSelected: {
    borderColor: "#126b75",
    borderWidth: 2
  },
  mutedCard: {
    marginVertical: 10
  },
  rowBetween: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12
  },
  flex: {
    flex: 1
  },
  kicker: {
    color: "#126b75",
    fontSize: 12,
    fontWeight: "800"
  },
  riskPill: {
    borderRadius: 999,
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "800",
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4
  },
  riskLow: {
    backgroundColor: "#24735a"
  },
  riskMedium: {
    backgroundColor: "#956a1d"
  },
  riskHigh: {
    backgroundColor: "#a34226"
  },
  riskBlocked: {
    backgroundColor: "#757575"
  },
  cardTitle: {
    color: "#172126",
    fontSize: 17,
    fontWeight: "800",
    marginTop: 12
  },
  secondaryText: {
    color: "#66747c",
    fontSize: 13,
    lineHeight: 19
  },
  bodyText: {
    color: "#314047",
    fontSize: 14,
    lineHeight: 20
  },
  metricRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 14
  },
  metricText: {
    color: "#172126",
    fontSize: 14,
    fontWeight: "800"
  },
  detail: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    marginBottom: 16,
    padding: 14
  },
  iconButton: {
    backgroundColor: "#e7f2f3",
    borderRadius: 8,
    justifyContent: "center",
    minHeight: ui.touchTarget,
    paddingHorizontal: 12,
    paddingVertical: 9
  },
  iconButtonText: {
    color: "#126b75",
    fontWeight: "800"
  },
  metricBand: {
    backgroundColor: "#f2f6f7",
    borderRadius: 8,
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 12,
    padding: 12
  },
  detailActions: {
    alignItems: "flex-end",
    gap: 8
  },
  timeline: {
    marginTop: 14,
    gap: 10
  },
  timelineRow: {
    flexDirection: "row",
    gap: 10
  },
  timelineIndex: {
    alignItems: "center",
    backgroundColor: "#126b75",
    borderRadius: 16,
    height: 32,
    justifyContent: "center",
    width: 32
  },
  timelineIndexText: {
    color: "#ffffff",
    fontWeight: "800"
  },
  timelineCopy: {
    flex: 1,
    paddingBottom: 4
  },
  timelineTitle: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  subheading: {
    color: "#172126",
    fontSize: 16,
    fontWeight: "800",
    marginTop: 18,
    marginBottom: 8
  },
  subheadingCompact: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  dataStatusPanel: {
    backgroundColor: "#eef5f6",
    borderLeftColor: "#126b75",
    borderLeftWidth: 4,
    borderRadius: 8,
    gap: 8,
    marginTop: 10,
    padding: 12
  },
  schedulePanel: {
    backgroundColor: "#f7fafb",
    borderRadius: 8,
    gap: 10,
    marginBottom: 12,
    padding: 12
  },
  scheduleHeader: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10
  },
  segmentedControl: {
    backgroundColor: "#e7f2f3",
    borderRadius: 8,
    flexDirection: "row",
    padding: 3
  },
  segmentedButton: {
    borderRadius: 6,
    minHeight: 36,
    justifyContent: "center",
    paddingHorizontal: 10,
    paddingVertical: 6
  },
  segmentedButtonActive: {
    backgroundColor: "#126b75"
  },
  segmentedButtonText: {
    color: "#126b75",
    fontSize: 13,
    fontWeight: "800"
  },
  segmentedButtonTextActive: {
    color: "#ffffff"
  },
  timeWheel: {
    alignItems: "center",
    flexDirection: "row",
    gap: 8,
    justifyContent: "center"
  },
  timeWheelColumn: {
    flex: 1,
    maxWidth: 132
  },
  timeWheelLabel: {
    color: "#66747c",
    fontSize: 12,
    fontWeight: "800",
    marginBottom: 6,
    textAlign: "center"
  },
  timeWheelScroll: {
    backgroundColor: "#ffffff",
    borderColor: "#dce4e6",
    borderRadius: 8,
    borderWidth: 1,
    height: 156
  },
  timeWheelContent: {
    paddingVertical: 6
  },
  timeWheelOption: {
    alignItems: "center",
    borderRadius: 6,
    height: 44,
    justifyContent: "center",
    marginHorizontal: 6,
    marginVertical: 2
  },
  timeWheelOptionSelected: {
    backgroundColor: "#126b75"
  },
  timeWheelOptionText: {
    color: "#314047",
    fontSize: 18,
    fontWeight: "800"
  },
  timeWheelOptionTextSelected: {
    color: "#ffffff"
  },
  timeWheelSeparator: {
    color: "#126b75",
    fontSize: 24,
    fontWeight: "800",
    paddingTop: 18
  },
  scheduleApplyRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: 10,
    justifyContent: "space-between"
  },
  selectedTimeButton: {
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderColor: "#dce4e6",
    borderRadius: 8,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 64,
    minWidth: 142,
    paddingHorizontal: 18,
    paddingVertical: 10
  },
  selectedTimeText: {
    color: "#172126",
    fontSize: 22,
    fontWeight: "800"
  },
  modalOverlay: {
    flex: 1,
    justifyContent: "flex-end"
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(10, 25, 31, 0.32)"
  },
  timeModalSheet: {
    backgroundColor: "#ffffff",
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
    gap: 14,
    padding: 16,
    paddingBottom: 22
  },
  modalCloseButton: {
    backgroundColor: "#e7f2f3",
    borderRadius: 8,
    justifyContent: "center",
    minHeight: ui.touchTarget,
    paddingHorizontal: 12,
    paddingVertical: 8
  },
  statusPill: {
    backgroundColor: "#d6e8ea",
    borderRadius: 999,
    color: "#126b75",
    fontSize: 12,
    fontWeight: "800",
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4
  },
  failureRow: {
    borderTopColor: "#dce8ea",
    borderTopWidth: 1,
    gap: 3,
    paddingTop: 8
  },
  costRow: {
    alignItems: "center",
    borderTopColor: "#edf0f1",
    borderTopWidth: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 10
  },
  costText: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  costValue: {
    alignItems: "flex-end"
  },
  estimateText: {
    color: "#956a1d",
    fontSize: 12,
    fontWeight: "800",
    marginTop: 2
  },
  retentionPanel: {
    backgroundColor: "#f7fafb",
    borderRadius: 8,
    gap: 10,
    marginTop: 12,
    padding: 12
  },
  retentionRow: {
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderRadius: 8,
    flexDirection: "row",
    gap: 10,
    minHeight: ui.touchTarget,
    padding: 10
  },
  notice: {
    backgroundColor: "#fff8e8",
    borderRadius: 8,
    marginBottom: 8,
    padding: 10
  },
  noticeTitle: {
    color: "#6f4a06",
    fontWeight: "800",
    marginBottom: 3
  },
  optionGroup: {
    borderColor: "#edf0f1",
    borderRadius: 8,
    borderWidth: 1,
    marginBottom: 10,
    padding: 10
  },
  optionTitle: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  expandText: {
    color: "#126b75",
    fontWeight: "800"
  },
  optionPanel: {
    gap: 8,
    marginTop: 10
  },
  transferSummary: {
    backgroundColor: "#f2f6f7",
    borderRadius: 8,
    padding: 10
  },
  optionButton: {
    backgroundColor: "#126b75",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 11
  },
  optionButtonDisabled: {
    backgroundColor: "#e1e7e8"
  },
  optionButtonText: {
    color: "#ffffff",
    fontWeight: "800",
    textAlign: "center"
  },
  optionButtonTextDisabled: {
    color: "#6e7d84"
  },
  feedbackPanel: {
    backgroundColor: "#f7fafb",
    borderRadius: 8,
    gap: 10,
    marginTop: 12,
    padding: 12
  },
  feedbackGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  feedbackButton: {
    backgroundColor: "#e7f2f3",
    borderRadius: 8,
    justifyContent: "center",
    minHeight: ui.touchTarget,
    paddingHorizontal: 12,
    paddingVertical: 9
  },
  toggleButtonActive: {
    backgroundColor: "#d6e8ea",
    borderColor: "#126b75",
    borderWidth: 1
  },
  candidate: {
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderRadius: 8,
    flexDirection: "row",
    gap: 12,
    marginTop: 10,
    padding: 12
  },
  candidateActive: {
    borderColor: "#126b75",
    borderWidth: 2
  },
  warningText: {
    color: "#9d2f21",
    fontSize: 12,
    marginTop: 4
  },
  emptyState: {
    alignItems: "flex-start",
    backgroundColor: "#ffffff",
    borderRadius: 8,
    gap: 10,
    marginTop: 24,
    padding: 16
  },
  emptyTitle: {
    color: "#172126",
    fontSize: 18,
    fontWeight: "800"
  },
  emptyButton: {
    backgroundColor: "#e7f2f3",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10
  },
  statePage: {
    alignItems: "flex-start",
    backgroundColor: "#ffffff",
    borderRadius: 8,
    gap: 12,
    marginTop: 12,
    padding: 16
  },
  errorStatePage: {
    backgroundColor: "#fff7f5"
  },
  stateTitle: {
    color: "#172126",
    fontSize: 20,
    fontWeight: "800"
  },
  worldMapCard: {
    backgroundColor: "#edf6f7",
    borderColor: "#d6e8ea",
    borderRadius: 8,
    borderWidth: 1,
    overflow: "hidden",
    padding: 10,
    width: "100%"
  },
  worldMapOcean: {
    aspectRatio: 1.3,
    backgroundColor: "#183b42",
    borderRadius: 8,
    minHeight: 238,
    overflow: "hidden",
    position: "relative",
    width: "100%"
  },
  worldMapLayer: {
    height: "100%",
    left: 0,
    position: "absolute",
    top: 0,
    width: "100%",
    transform: [{ scale: 1.02 }]
  },
  worldMapBaseLayer: {
    opacity: 0.96,
    zIndex: 0
  },
  worldMapFlowClip: {
    bottom: 0,
    left: 0,
    overflow: "hidden",
    position: "absolute",
    top: 0,
    zIndex: 1
  },
  worldMapFlowGlowLayer: {
    opacity: 0.14,
    transform: [{ scale: 1.04 }]
  },
  worldMapFlowLayer: {
    opacity: 1
  },
  actionRow: {
    flexDirection: "row",
    gap: 10
  },
  actionRowWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8
  },
  primarySmallButton: {
    backgroundColor: ui.colors.teal,
    borderRadius: ui.radius.control,
    minHeight: ui.touchTarget,
    paddingHorizontal: 14,
    paddingVertical: 10,
    justifyContent: "center"
  },
  primarySmallButtonText: {
    color: "#ffffff",
    fontWeight: "800"
  },
  secondarySmallButton: {
    backgroundColor: ui.colors.tealSoft,
    borderRadius: ui.radius.control,
    minHeight: ui.touchTarget,
    paddingHorizontal: 12,
    paddingVertical: 10,
    justifyContent: "center"
  },
  headerActions: {
    alignItems: "center",
    flexDirection: "row",
    gap: 8
  },
  sourceButton: {
    backgroundColor: ui.colors.tealSoft,
    borderRadius: ui.radius.control,
    minHeight: ui.touchTarget,
    justifyContent: "center",
    paddingHorizontal: 10,
    paddingVertical: 7
  },
  requestIdText: {
    color: "#172126",
    fontSize: 13,
    fontWeight: "800",
    lineHeight: 19
  },
  sourceCard: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    gap: 8,
    marginTop: 10,
    padding: 12
  },
  sourceFailureCard: {
    backgroundColor: "#fff8e8",
    borderRadius: 8,
    gap: 8,
    marginTop: 10,
    padding: 12
  },
  bottomTabs: {
    backgroundColor: "#ffffff",
    borderTopColor: "#dce4e6",
    borderTopWidth: 1,
    flexDirection: "row",
    gap: 10,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 12
  },
  tabButton: {
    alignItems: "center",
    borderRadius: 8,
    flex: 1,
    justifyContent: "center",
    minHeight: 52,
    paddingVertical: 7
  },
  tabButtonActive: {
    backgroundColor: "#e7f2f3"
  },
  tabLabel: {
    color: "#66747c",
    fontSize: 14,
    fontWeight: "800",
    lineHeight: 20
  },
  tabTextActive: {
    color: "#126b75"
  }
});
