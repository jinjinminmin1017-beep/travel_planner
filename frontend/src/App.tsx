import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  ImageBackground,
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
import { bookingRedirect, cancelPlanningJob, planTripAsync, pollPlanningJob, recalculate, retryPlanningJob, submitFeedback, trackEvent } from "./api/client";
import { ui } from "./designSystem";
import {
  copyPlanSummary,
  hasExpiredRedirect,
  loadFavoritePlanSnapshots,
  loadRecentPlanSnapshots,
  loadRetentionPreferences,
  openExternalUrl,
  type RecentPlanSnapshot,
  requestLocationPermission,
  saveRecentPlanSnapshot,
  saveRetentionPreferences,
  sharePlan,
  toggleFavoritePlanSnapshot
} from "./nativeCapabilities";
import type { DataSourceMetadata, DestinationPresentation, FeedbackCategory, LocalTransferOption, RecalculateChangeType, RecalculateResponse, RecommendationSlot, Segment, SourceFailure, TimePoint, TravelPlan, TravelPlanResponse, TravelRequest } from "./types";
import { formatMoney, minutesToText, riskLabel, slotLabel } from "./utils/format";

const HERO_IMAGES: Record<string, ImageSourcePropType> = {
  qingdao: qingdaoHero
};

type ActiveTab = "input" | "results";
type ResultsPane = "overview" | "sources";
type TimeAnchor = "DEPARTURE" | "ARRIVAL";

const POLL_INTERVAL_MS = 1200;
const MAX_POLL_ATTEMPTS = 100;
const ACTIVE_PLANNING_STATUSES = new Set(["PENDING", "RUNNING"]);
const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "RUNNING", "WAITING_SOURCE"]);

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

function transferModeLabel(mode: string) {
  const normalized = mode.replace("transfer_", "").toUpperCase();
  if (normalized === "TAXI") return "打车";
  if (normalized === "SUBWAY") return "地铁";
  if (normalized === "BUS") return "公交";
  if (normalized === "WALK") return "步行";
  return mode.replace("transfer_", "");
}

function formatTimePoint(time?: TimePoint | null) {
  if (!time?.datetime) return "时间待确认";
  const parsed = new Date(time.datetime);
  if (Number.isNaN(parsed.getTime())) return time.datetime;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(parsed);
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

function segmentTimeLabel(segment: Segment) {
  const departure = formatClockTime(segment.departure_time);
  const arrival = formatClockTime(segment.arrival_time);
  if (departure && arrival) {
    return `${departure} - ${arrival}`;
  }
  if (departure) return `${departure} 出发`;
  if (arrival) return `${arrival} 到达`;
  return null;
}

function sourceFreshnessLabel(source?: DataSourceMetadata | null) {
  if (!source) return "来源待确认";
  return `${source.source_name} · ${source.license_status} · 更新 ${formatTimePoint(source.fetched_at)}`;
}

function latestSource(plan: TravelPlan) {
  return [...plan.data_sources].sort((left, right) => new Date(right.fetched_at.datetime).getTime() - new Date(left.fetched_at.datetime).getTime())[0] ?? null;
}

function segmentTitle(segment: Segment) {
  if (segment.segment_type === "RAIL") return `${segment.train_number} ${segment.origin_station} 到 ${segment.destination_station}`;
  if (segment.segment_type === "FLIGHT") return `${segment.flight_number} ${segment.origin_airport} 到 ${segment.destination_airport}`;
  return `${transferModeLabel(segment.transfer_mode ?? "")} ${segment.origin} 到 ${segment.destination}`;
}

function segmentModeLabel(segment: Segment) {
  if (segment.segment_type === "LOCAL_TRANSFER") return transferModeLabel(segment.transfer_mode ?? "");
  if (segment.segment_type === "RAIL") return "高铁";
  if (segment.segment_type === "FLIGHT") return "航班";
  return segment.segment_type;
}

function segmentMetaLabel(segment: Segment) {
  const parts = [segmentModeLabel(segment), segmentTimeLabel(segment), minutesToText(segment.duration_minutes)];
  return parts.filter(Boolean).join(" · ");
}

function planDisplayName(plan: TravelPlan) {
  const originalParts = plan.plan_name.split("+").map((part) => part.trim());
  if (originalParts.length === plan.segments.length) {
    return plan.segments.map((segment, index) => (segment.segment_type === "LOCAL_TRANSFER" ? segmentModeLabel(segment) : originalParts[index])).join(" + ");
  }
  return plan.segments.map(segmentModeLabel).join(" + ");
}

function fallbackTransferOption(segment: Segment, optionId: string): LocalTransferOption {
  const mode = optionId.replace("transfer_", "").toUpperCase();
  const label = transferModeLabel(optionId);
  return {
    option_id: optionId,
    transfer_mode: mode,
    label,
    estimated_cost: segment.estimated_cost ?? { amount_minor: 0, currency: "CNY", scale: 2, is_estimated: true, display_text: "待估算" },
    duration_minutes: segment.duration_minutes,
    access_station: mode === "TAXI" ? null : `${segment.origin ?? "出发地"}附近${mode === "SUBWAY" ? "地铁站" : "公交站"}`,
    egress_station: mode === "TAXI" ? null : `${segment.destination ?? "目的地"}附近${mode === "SUBWAY" ? "地铁站" : "公交站"}`,
    access_instruction: mode === "TAXI" ? `从 ${segment.origin} 上车。` : `从 ${segment.origin} 前往上车站点。`,
    ride_instruction: mode === "TAXI" ? `直达 ${segment.destination}。` : `乘坐${label}到下车站点。`,
    egress_instruction: mode === "TAXI" ? `在 ${segment.destination} 下车。` : `从下车站点前往 ${segment.destination}。`,
    walking_distance_meters: 0,
    data_source: segment.data_source
  };
}

function transferOptionsFor(segment: Segment) {
  return segment.transfer_options?.length ? segment.transfer_options : segment.available_options?.map((option) => fallbackTransferOption(segment, option)) ?? [];
}

function selectedTransferOption(segment: Segment) {
  return transferOptionsFor(segment).find((option) => option.option_id === segment.option_id) ?? transferOptionsFor(segment)[0] ?? null;
}

function selectedRailSeat(segment: Segment) {
  return segment.seat_options?.find((option) => option.option_id === segment.selected_seat_option_id) ?? segment.seat_options?.[0] ?? null;
}

function selectedFlightCabin(segment: Segment) {
  return segment.cabin_options?.find((option) => option.option_id === segment.selected_cabin_option_id) ?? segment.cabin_options?.[0] ?? null;
}

function percentLabel(value: number) {
  return `${Math.round(value * 100)}%`;
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

function Hero({ presentation, plan }: { presentation: DestinationPresentation | null; plan: TravelPlan | null }) {
  const destinationKey = presentation?.destination_key ?? "generic";
  const imageSource = HERO_IMAGES[destinationKey];
  const content = (
    <View style={styles.heroShade}>
      <Text style={styles.heroKicker}>目的地</Text>
      <Text style={styles.heroTitle}>{presentation?.display_name ?? "出行搭子"}</Text>
      {plan && (
        <Text style={styles.heroMeta}>
          {planDisplayName(plan)} · {minutesToText(plan.total_duration_minutes)} · {formatMoney(plan.cost_breakdown.total_cost)}
        </Text>
      )}
    </View>
  );

  if (!imageSource) {
    return <View style={[styles.hero, styles.heroFallback]}>{content}</View>;
  }
  return (
    <ImageBackground source={imageSource} style={styles.hero} imageStyle={styles.heroImage}>
      {content}
    </ImageBackground>
  );
}

function RecommendationCard({ slot, plan, selected, onSelect }: { slot: RecommendationSlot; plan: TravelPlan | null; selected: boolean; onSelect: (plan: TravelPlan) => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={plan ? `${slotLabel(slot.recommendation_type)}：${planDisplayName(plan)}，${riskLabel(plan.risk_assessment.overall_risk_level)}` : `${slotLabel(slot.recommendation_type)}不可用`}
      accessibilityState={{ selected, disabled: !plan }}
      hitSlop={ui.hitSlop}
      style={[styles.card, styles.recommendationCard, selected && styles.cardSelected]}
      disabled={!plan}
      onPress={() => plan && onSelect(plan)}
    >
      <View style={styles.rowBetween}>
        <Text style={styles.kicker}>{slotLabel(slot.recommendation_type)}</Text>
        <Text style={[styles.riskPill, riskStyle(plan?.risk_assessment.overall_risk_level ?? slot.status)]}>{plan ? riskLabel(plan.risk_assessment.overall_risk_level) : slot.status}</Text>
      </View>
      {plan ? (
        <>
          <Text style={styles.cardTitle}>{planDisplayName(plan)}</Text>
          <Text style={styles.secondaryText}>{planTypeLabel(plan.plan_type)}</Text>
          <View style={styles.metricRow}>
            <Text style={styles.metricText}>{formatMoney(plan.cost_breakdown.total_cost)}</Text>
            <Text style={styles.metricText}>{minutesToText(plan.total_duration_minutes)}</Text>
          </View>
        </>
      ) : (
        <Text style={styles.cardTitle}>{slot.reason || "当前不可推荐"}</Text>
      )}
    </Pressable>
  );
}

function SegmentTimeline({ segments }: { segments: Segment[] }) {
  return (
    <View style={styles.timeline}>
      {segments.map((segment, index) => (
        <View style={styles.timelineRow} key={segment.segment_id}>
          <View style={styles.timelineIndex}>
            <Text style={styles.timelineIndexText}>{index + 1}</Text>
          </View>
          <View style={styles.timelineCopy}>
            <Text style={styles.timelineTitle}>{segmentTitle(segment)}</Text>
            <Text style={styles.secondaryText}>{segmentMetaLabel(segment)}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

function TransferRouteSummary({ option }: { option: LocalTransferOption }) {
  return (
    <View style={styles.transferSummary}>
      {(option.access_station || option.egress_station) && (
        <Text style={styles.secondaryText}>
          {option.access_station ?? "上车点"} 到 {option.egress_station ?? "下车点"}
        </Text>
      )}
      <Text style={styles.bodyText}>
        {option.access_instruction} {option.ride_instruction} {option.egress_instruction}
      </Text>
    </View>
  );
}

function DataStatusPanel({ response, onRetrySources, retrying }: { response: TravelPlanResponse; onRetrySources?: () => void; retrying?: boolean }) {
  const firstFailures = response.source_failures.slice(0, 3);
  const hasContent = response.user_visible_warnings.length > 0 || response.missing_components.length > 0 || firstFailures.length > 0;
  if (!hasContent) return null;

  return (
    <View style={styles.dataStatusPanel}>
      <View style={styles.rowBetween}>
        <Text style={styles.subheadingCompact}>数据状态</Text>
        <Text style={styles.statusPill}>{response.planning_status}</Text>
      </View>
      {response.user_visible_warnings.map((warning) => (
        <Text style={styles.bodyText} key={warning}>{warning}</Text>
      ))}
      {response.missing_components.length > 0 && (
        <Text style={styles.secondaryText}>缺失：{response.missing_components.join("、")}</Text>
      )}
      {firstFailures.map((failure) => (
        <View style={styles.failureRow} key={failure.failure_id}>
          <Text style={styles.noticeTitle}>{failure.source_id}</Text>
          <Text style={styles.secondaryText}>{failure.user_visible_message}</Text>
          {failure.fallback_used && <Text style={styles.secondaryText}>下一步：可继续查看候选，跳转后以第三方平台确认为准。</Text>}
        </View>
      ))}
      {response.async_job && onRetrySources && firstFailures.length > 0 && (
        <Pressable accessibilityRole="button" accessibilityLabel="重试失败的数据来源" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={onRetrySources} disabled={retrying}>
          <Text style={styles.iconButtonText}>{retrying ? "重试中" : "重试来源"}</Text>
        </Pressable>
      )}
    </View>
  );
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
  const [anchor, setAnchor] = useState<TimeAnchor>(initialAnchor);
  const [clockValue, setClockValue] = useState(() => clockInputValue(initialAnchor === "ARRIVAL" ? plan?.arrival_time ?? response.travel_request.latest_arrival_time : plan?.departure_time ?? response.travel_request.earliest_departure_time));

  useEffect(() => {
    const nextAnchor: TimeAnchor = response.travel_request.time_anchor_type === "ARRIVAL" ? "ARRIVAL" : "DEPARTURE";
    setAnchor(nextAnchor);
    setClockValue(clockInputValue(nextAnchor === "ARRIVAL" ? plan?.arrival_time ?? response.travel_request.latest_arrival_time : plan?.departure_time ?? response.travel_request.earliest_departure_time));
  }, [response.request_id, plan?.plan_id]);

  function apply() {
    if (!parseClockInput(clockValue)) {
      Alert.alert("时间格式不对", "请按 HH:mm 输入，例如 09:30。");
      return;
    }
    onApply(anchor, clockValue);
  }

  return (
    <View style={styles.schedulePanel}>
      <View style={styles.scheduleHeader}>
        <Text style={styles.subheadingCompact}>时间</Text>
        <View style={styles.segmentedControl}>
          {(["DEPARTURE", "ARRIVAL"] as TimeAnchor[]).map((item) => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={item === "DEPARTURE" ? "按主程出发时间重新规划" : "按最晚到达时间重新规划"}
              accessibilityState={{ selected: anchor === item }}
              hitSlop={ui.hitSlop}
              key={item}
              style={[styles.segmentedButton, anchor === item && styles.segmentedButtonActive]}
              onPress={() => setAnchor(item)}
            >
              <Text style={[styles.segmentedButtonText, anchor === item && styles.segmentedButtonTextActive]}>{item === "DEPARTURE" ? "主程出发" : "最晚到达"}</Text>
            </Pressable>
          ))}
        </View>
      </View>
      <View style={styles.scheduleInputRow}>
        <TextInput
          accessibilityLabel="时间，格式为小时冒号分钟"
          style={[styles.compactInput, styles.timeInput]}
          value={clockValue}
          onChangeText={setClockValue}
          placeholder="09:30"
          keyboardType="numbers-and-punctuation"
        />
        <Pressable accessibilityRole="button" accessibilityLabel="按当前时间重新规划" hitSlop={ui.hitSlop} style={styles.primarySmallButton} onPress={apply} disabled={loading}>
          <Text style={styles.primarySmallButtonText}>{loading ? "规划中" : "重新规划"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function PlanningScreen({ progress = 0, onCancel }: { progress?: number; onCancel?: () => void }) {
  const stages = ["解析", "地点", "接驳", "铁路", "航班", "评分", "推荐"];
  const normalizedProgress = Math.max(0, Math.min(100, Math.round(progress)));
  const completedStages = new Set(normalizedProgress >= 100 ? stages : normalizedProgress > 0 ? ["解析"] : []);
  return (
    <View style={styles.statePage}>
      <ActivityIndicator color="#126b75" size="large" />
      <Text style={styles.stateTitle}>正在规划</Text>
      <Text style={styles.secondaryText}>当前进度 {normalizedProgress}%</Text>
      <View style={styles.stageList}>
        {stages.map((stage) => {
          const completed = completedStages.has(stage);
          return (
            <View accessible accessibilityLabel={`${stage}${completed ? "已完成" : "未完成"}`} style={styles.stageItem} key={stage}>
              <View style={[styles.stageDot, completed ? styles.stageDotComplete : styles.stageDotPending]} />
              <Text style={styles.bodyText}>{stage}</Text>
            </View>
          );
        })}
      </View>
      {onCancel && (
        <Pressable accessibilityRole="button" accessibilityLabel="取消当前规划任务" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={onCancel}>
          <Text style={styles.iconButtonText}>取消规划</Text>
        </Pressable>
      )}
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
        <Pressable accessibilityRole="button" accessibilityLabel="返回方案详情" hitSlop={ui.hitSlop} style={styles.secondarySmallButton} onPress={onBack}>
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

function TicketEnhancementPanel({ plan }: { plan: TravelPlan }) {
  if (!plan.ticket_enhancement) return null;
  const ticket = plan.ticket_enhancement;
  return (
    <View style={styles.notice}>
      <View style={styles.rowBetween}>
        <Text style={styles.noticeTitle}>票源增强 {ticket.grade}</Text>
        <Text style={styles.statusPill}>{riskLabel(ticket.risk_level)}</Text>
      </View>
      <Text style={styles.bodyText}>{ticket.recommendation_message}</Text>
      <Text style={styles.secondaryText}>
        实乘 {ticket.actual_origin} 到 {ticket.actual_destination}；购票区间 {ticket.ticket_origin} 到 {ticket.ticket_destination}
      </Text>
      <Text style={styles.secondaryText}>
        额外成本 {formatMoney(ticket.extra_cost)} · 未乘区间 {percentLabel(ticket.unused_distance_ratio)}
      </Text>
      {ticket.requires_onboard_supplement && <Text style={styles.warningText}>可能需要车上补票或人工确认，跳转后以官方平台和现场规则为准。</Text>}
      <Text style={styles.secondaryText}>{sourceFreshnessLabel(ticket.data_source)}</Text>
    </View>
  );
}

const FEEDBACK_OPTIONS: Array<{ category: FeedbackCategory; label: string }> = [
  { category: "ROUTE_INACCURATE", label: "路线不准" },
  { category: "PRICE_INACCURATE", label: "价格不准" },
  { category: "REDIRECT_FAILED", label: "跳转失败" },
  { category: "HARD_TO_UNDERSTAND", label: "看不懂" }
];

function FeedbackPanel({ response, plan }: { response: TravelPlanResponse; plan: TravelPlan }) {
  const [busyCategory, setBusyCategory] = useState<FeedbackCategory | null>(null);

  async function send(category: FeedbackCategory) {
    setBusyCategory(category);
    try {
      const feedback = await submitFeedback({
        requestId: response.request_id,
        traceId: response.trace_id,
        correlationId: response.correlation_id,
        planId: plan.plan_id,
        sourceId: latestSource(plan)?.source_id ?? null,
        category
      });
      void trackEvent({ eventType: "FEEDBACK_SUBMITTED", requestId: response.request_id, traceId: response.trace_id, planId: plan.plan_id, metadata: { category } }).catch(() => undefined);
      Alert.alert("已收到", `反馈编号 ${feedback.feedback_id}`);
    } catch (error) {
      Alert.alert("反馈失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusyCategory(null);
    }
  }

  return (
    <View style={styles.feedbackPanel}>
      <Text style={styles.subheadingCompact}>问题反馈</Text>
      <View style={styles.feedbackGrid}>
        {FEEDBACK_OPTIONS.map((option) => (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`反馈${option.label}`}
            hitSlop={ui.hitSlop}
            key={option.category}
            style={styles.feedbackButton}
            disabled={busyCategory !== null}
            onPress={() => send(option.category)}
          >
            <Text style={styles.iconButtonText}>{busyCategory === option.category ? "提交中" : option.label}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.secondaryText}>反馈会关联 request_id、trace_id 和当前方案，不需要填写账号或支付信息。</Text>
    </View>
  );
}

function DetailPanel({
  response,
  plan,
  favorite,
  onFavoriteToggle,
  onRecalculated
}: {
  response: TravelPlanResponse;
  plan: TravelPlan;
  favorite: boolean;
  onFavoriteToggle: (plan: TravelPlan) => void;
  onRecalculated: (response: RecalculateResponse) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [expandedSegmentId, setExpandedSegmentId] = useState<string | null>(null);

  async function applyOption(segment: Segment, changeType: RecalculateChangeType, optionId: string, label: string) {
    setBusy(true);
    try {
      const response = await recalculate(plan.plan_id, segment.segment_id, changeType, optionId, label);
      onRecalculated(response);
      Alert.alert("已重算", `${response.change_summary.message} ${response.change_summary.cost_delta.display_text}`);
    } catch (error) {
      Alert.alert("重算失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function openRedirect() {
    const first = plan.segments.find((segment) => segment.segment_type === "RAIL" || segment.segment_type === "FLIGHT");
    const redirectType = first?.segment_type === "FLIGHT" ? "AIRLINE" : "RAIL_12306";
    setBusy(true);
    try {
      const redirectResponse = await bookingRedirect(plan.plan_id, first?.segment_id ?? null, redirectType);
      void trackEvent({ eventType: "REDIRECT_CLICK", requestId: response.request_id, traceId: response.trace_id, planId: plan.plan_id, metadata: { redirectType } }).catch(() => undefined);
      if (redirectResponse.redirect.url_available && redirectResponse.redirect.url) {
        const opened = await openExternalUrl(redirectResponse.redirect.url);
        if (!opened.opened) {
          Alert.alert("请手动确认", redirectResponse.redirect.fallback_instruction ?? opened.message ?? "请打开对应平台确认。");
        }
      } else {
        Alert.alert("请手动确认", redirectResponse.redirect.fallback_instruction ?? "请打开对应平台确认。");
      }
    } catch (error) {
      Alert.alert("跳转失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function shareCurrentPlan() {
    try {
      await sharePlan(plan);
    } catch (error) {
      Alert.alert("分享失败", error instanceof Error ? error.message : "请稍后重试。");
    }
  }

  async function copyCurrentPlan() {
    try {
      const copied = await copyPlanSummary(plan);
      Alert.alert(copied ? "已复制" : "无法直接复制", copied ? "行程摘要已复制。" : "当前平台没有剪贴板能力，可使用分享入口。");
    } catch (error) {
      Alert.alert("复制失败", error instanceof Error ? error.message : "请稍后重试。");
    }
  }

  return (
    <View style={styles.detail}>
      <View style={styles.rowBetween}>
        <View style={styles.flex}>
          <Text style={styles.kicker}>{planTypeLabel(plan.plan_type)}</Text>
          <Text style={styles.sectionTitle}>{planDisplayName(plan)}</Text>
        </View>
        <View style={styles.detailActions}>
          <Pressable accessibilityRole="button" accessibilityLabel={favorite ? "取消收藏当前方案" : "收藏当前方案"} hitSlop={ui.hitSlop} style={styles.iconButton} onPress={() => onFavoriteToggle(plan)} disabled={busy}>
            <Text style={styles.iconButtonText}>{favorite ? "已收藏" : "收藏"}</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="分享行程摘要" hitSlop={ui.hitSlop} style={styles.iconButton} onPress={shareCurrentPlan} disabled={busy}>
            <Text style={styles.iconButtonText}>分享</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="复制行程摘要" hitSlop={ui.hitSlop} style={styles.iconButton} onPress={copyCurrentPlan} disabled={busy}>
            <Text style={styles.iconButtonText}>复制</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="跳转到第三方平台确认" hitSlop={ui.hitSlop} style={styles.iconButton} onPress={openRedirect} disabled={busy}>
            <Text style={styles.iconButtonText}>跳转</Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.metricBand}>
        <Text style={styles.metricText}>{formatMoney(plan.cost_breakdown.total_cost)}</Text>
        <Text style={styles.metricText}>{minutesToText(plan.total_duration_minutes)}</Text>
      </View>

      <SegmentTimeline segments={plan.segments} />

      <Text style={styles.subheading}>费用明细</Text>
      {plan.cost_breakdown.items.map((item) => (
        <View style={styles.costRow} key={`${item.label}-${item.amount.amount_minor}`}>
          <Text style={styles.bodyText}>{item.label}</Text>
          <View style={styles.costValue}>
            <Text style={styles.costText}>{formatMoney(item.amount)}</Text>
            {item.amount.is_estimated && <Text style={styles.estimateText}>估算</Text>}
          </View>
        </View>
      ))}

      <TicketEnhancementPanel plan={plan} />

      <Text style={styles.subheading}>可调整选项</Text>
      {plan.segments.map((segment) => {
        const expanded = expandedSegmentId === segment.segment_id;
        const transferOption = segment.segment_type === "LOCAL_TRANSFER" ? selectedTransferOption(segment) : null;
        const railSeat = segment.segment_type === "RAIL" ? selectedRailSeat(segment) : null;
        const flightCabin = segment.segment_type === "FLIGHT" ? selectedFlightCabin(segment) : null;
        return (
          <View style={styles.optionGroup} key={segment.segment_id}>
            <Pressable accessibilityRole="button" accessibilityLabel={`${expanded ? "收起" : "展开"}${segmentTitle(segment)}的可调整选项`} hitSlop={ui.hitSlop} style={styles.rowBetween} onPress={() => setExpandedSegmentId(expanded ? null : segment.segment_id)}>
              <View style={styles.flex}>
                <Text style={styles.optionTitle}>{segmentTitle(segment)}</Text>
                {transferOption && <Text style={styles.secondaryText}>{transferOption.label} · {formatMoney(transferOption.estimated_cost)}</Text>}
                {railSeat && <Text style={styles.secondaryText}>{railSeat.seat_type} · {formatMoney(railSeat.price)}</Text>}
                {flightCabin && <Text style={styles.secondaryText}>{flightCabin.cabin_type} · {formatMoney(flightCabin.price)}</Text>}
              </View>
              <Text style={styles.expandText}>{expanded ? "收起" : "展开"}</Text>
            </Pressable>

            {expanded && (
              <View style={styles.optionPanel}>
                {transferOption && <TransferRouteSummary option={transferOption} />}
                {segment.seat_options?.map((option) => (
                  <OptionButton
                    key={option.option_id}
                    disabled={busy || option.option_id === segment.selected_seat_option_id}
                    label={`${option.seat_type} ${formatMoney(option.price)}`}
                    onPress={() => applyOption(segment, "SEAT_TYPE", option.option_id, option.seat_type)}
                  />
                ))}
                {segment.cabin_options?.map((option) => (
                  <OptionButton
                    key={option.option_id}
                    disabled={busy || option.option_id === segment.selected_cabin_option_id}
                    label={`${option.cabin_type} ${formatMoney(option.price)}`}
                    onPress={() => applyOption(segment, "CABIN_TYPE", option.option_id, option.cabin_type)}
                  />
                ))}
                {segment.segment_type === "LOCAL_TRANSFER" && transferOptionsFor(segment).map((option) => (
                  <OptionButton
                    key={option.option_id}
                    disabled={busy || option.option_id === segment.option_id}
                    label={`${option.label} ${formatMoney(option.estimated_cost)} · ${minutesToText(option.duration_minutes)}`}
                    onPress={() => applyOption(segment, "LOCAL_TRANSFER_MODE", option.option_id, option.label)}
                  />
                ))}
              </View>
            )}
          </View>
        );
      })}
      <FeedbackPanel response={response} plan={plan} />
    </View>
  );
}

function OptionButton({ label, disabled, onPress }: { label: string; disabled?: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} hitSlop={ui.hitSlop} style={[styles.optionButton, disabled && styles.optionButtonDisabled]} disabled={disabled} onPress={onPress}>
      <Text style={[styles.optionButtonText, disabled && styles.optionButtonTextDisabled]}>{label}</Text>
    </Pressable>
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

function riskStyle(level: string) {
  if (level === "LOW") return styles.riskLow;
  if (level === "MEDIUM") return styles.riskMedium;
  if (level === "HIGH") return styles.riskHigh;
  return styles.riskBlocked;
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

  async function pollUntilSettled(initialResponse: TravelPlanResponse, runId: number) {
    let current = initialResponse;
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      if (runId !== planningRunId.current) return;
      if (!current.async_job?.polling_url || !isPlanningActive(current)) return;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      if (runId !== planningRunId.current) return;
      current = await pollPlanningJob(current.async_job.polling_url);
      setResponse(current);
      syncSelection(current);
      if (!isPlanningActive(current)) {
        void trackEvent({
          eventType: current.planning_status === "PARTIAL" ? "PLANNING_PARTIAL" : "PLANNING_SUCCESS",
          requestId: current.request_id,
          traceId: current.trace_id,
          planId: current.plans[0]?.plan_id ?? null,
          metadata: { planning_status: current.planning_status }
        }).catch(() => undefined);
        return;
      }
    }
    setError("规划仍在进行中，请稍后重试或改写需求。");
  }

  async function startPlanning(input: string | TravelRequest, metadata: Record<string, unknown> = {}) {
    setLoading(true);
    setError("");
    setResponse(null);
    setResultsPane("overview");
    setActiveTab("results");
    const runId = planningRunId.current + 1;
    planningRunId.current = runId;
    try {
      void trackEvent({ eventType: "INPUT_SUBMITTED", metadata }).catch(() => undefined);
      const result = await planTripAsync(input);
      setResponse(result);
      syncSelection(result);
      await pollUntilSettled(result, runId);
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
    await startPlanning(request, { source: "time_adjustment", time_anchor_type: anchor, time_value: value });
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
      setResponse(result);
      syncSelection(result);
      await pollUntilSettled(result, runId);
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
            <View style={styles.topbar}>
              <Text style={styles.appTitle}>路明</Text>
              <Text style={styles.appSubtitle}>{loading ? "正在把需求拆成门到门方案。" : "云开见路，每条方案都保留来源和边界。"}</Text>
            </View>

            {loading && (!response || response.plans.length === 0) ? (
              <PlanningScreen progress={response?.progress ?? 0} onCancel={response?.async_job ? cancelCurrentJob : undefined} />
            ) : error ? (
              <ErrorState message={error} onRetry={submit} onEdit={() => setActiveTab("input")} />
            ) : !response ? (
              <View style={styles.emptyState}>
                <Text style={styles.emptyTitle}>还没有规划结果</Text>
                <Text style={styles.secondaryText}>先到云起写下出发地、目的地和时间，提交后会自动切到这里。</Text>
                <Pressable accessibilityRole="button" accessibilityLabel="前往云起输入页" hitSlop={ui.hitSlop} style={styles.emptyButton} onPress={() => setActiveTab("input")}>
                  <Text style={styles.iconButtonText}>去云起</Text>
                </Pressable>
              </View>
            ) : response.plans.length === 0 ? (
              <EmptyResults response={response} onEdit={() => setActiveTab("input")} />
            ) : resultsPane === "sources" ? (
              <DataSourcesPage response={response} plan={selectedPlan} onBack={() => setResultsPane("overview")} />
            ) : (
              <>
                <Hero presentation={response.destination_presentation ?? null} plan={selectedPlan} />

                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>推荐方案</Text>
                  <View style={styles.headerActions}>
                    <Text style={styles.secondaryText}>{response.planning_status}</Text>
                    <Pressable accessibilityRole="button" accessibilityLabel="查看数据来源" hitSlop={ui.hitSlop} style={styles.sourceButton} onPress={() => setResultsPane("sources")}>
                      <Text style={styles.iconButtonText}>来源</Text>
                    </Pressable>
                  </View>
                </View>
                <DataStatusPanel response={response} onRetrySources={retrySources} retrying={loading} />
                {recommendations.length === 0 && (
                  <View style={[styles.card, styles.mutedCard]}>
                    <Text style={styles.cardTitle}>推荐暂不可用</Text>
                    <Text style={styles.secondaryText}>系统未使用代码生成三张推荐卡，你仍可以查看候选方案。</Text>
                  </View>
                )}
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                  {recommendations.map((slot) => (
                    <RecommendationCard
                      key={slot.recommendation_type}
                      slot={slot}
                      plan={findPlan(response, slot.plan_id)}
                      selected={slot.plan_id === selectedPlan?.plan_id}
                      onSelect={(plan) => {
                        setSelectedPlanId(plan.plan_id);
                        void trackEvent({ eventType: "RECOMMENDATION_CLICK", requestId: response.request_id, traceId: response.trace_id, planId: plan.plan_id, metadata: { recommendation_type: slot.recommendation_type } }).catch(() => undefined);
                      }}
                    />
                  ))}
                </ScrollView>

                <ScheduleAdjustPanel response={response} plan={selectedPlan} loading={loading} onApply={replanWithTime} />

                {selectedPlan && (
                  <DetailPanel
                    response={response}
                    plan={selectedPlan}
                    favorite={selectedPlanFavorite}
                    onFavoriteToggle={toggleFavorite}
                    onRecalculated={replacePlan}
                  />
                )}

                <Text style={styles.sectionTitle}>候选方案</Text>
                {candidatePlans.map((plan) => (
                  <Pressable accessibilityRole="button" accessibilityLabel={`选择候选方案：${planDisplayName(plan)}`} hitSlop={ui.hitSlop} style={[styles.candidate, plan.plan_id === selectedPlan?.plan_id && styles.candidateActive]} key={plan.plan_id} onPress={() => setSelectedPlanId(plan.plan_id)}>
                    <View style={styles.flex}>
                      <Text style={styles.optionTitle}>{planDisplayName(plan)}</Text>
                      <Text style={styles.secondaryText}>
                        {planTypeLabel(plan.plan_type)} · {riskLabel(plan.risk_assessment.overall_risk_level)}
                      </Text>
                      {!plan.can_be_selected_by_llm && <Text style={styles.warningText}>{plan.block_reason_message ?? "不进入主推荐"}</Text>}
                    </View>
                    <Text style={styles.costText}>{formatMoney(plan.cost_breakdown.total_cost)}</Text>
                  </Pressable>
                ))}
              </>
            )}
          </ScrollView>
        )}

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
  scheduleInputRow: {
    alignItems: "center",
    flexDirection: "row",
    gap: 10
  },
  timeInput: {
    flex: 1,
    minHeight: ui.touchTarget
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
  stageList: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    width: "100%"
  },
  stageItem: {
    alignItems: "center",
    flexDirection: "row",
    gap: 6,
    minHeight: 24
  },
  stageDot: {
    borderColor: "#126b75",
    borderRadius: 6,
    borderWidth: 2,
    height: 12,
    width: 12
  },
  stageDotComplete: {
    backgroundColor: "#126b75"
  },
  stageDotPending: {
    backgroundColor: "#ffffff"
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
