import { useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { bookingRedirect, recalculate, submitFeedback, trackEvent } from "../../api/client";
import { ui } from "../../designSystem";
import { copyPlanSummary, openExternalUrl, sharePlan } from "../../nativeCapabilities";
import type { FeedbackCategory, RecalculateChangeType, RecalculateResponse, Segment, TravelPlan, TravelPlanResponse } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";
import { buildOfficialRedirectPresentation, buildRouteCostPresentation } from "../../utils/routePlanning";
import { JourneyCostSummary } from "./JourneyCostSummary";
import { JourneyLegCard } from "./JourneyLegCard";
import { formatClockTime } from "./presentation";

type Props = {
  response: TravelPlanResponse;
  plan: TravelPlan;
  favorite: boolean;
  onBack: () => void;
  onSources: () => void;
  onFavoriteToggle: (plan: TravelPlan) => void;
  onRecalculated: (response: RecalculateResponse) => void;
};

const FEEDBACK_OPTIONS: Array<{ category: FeedbackCategory; label: string }> = [
  { category: "ROUTE_INACCURATE", label: "路线不准" },
  { category: "PRICE_INACCURATE", label: "价格不准" },
  { category: "REDIRECT_FAILED", label: "跳转失败" },
  { category: "HARD_TO_UNDERSTAND", label: "看不懂" }
];

export function RouteDetailScreen({ response, plan, favorite, onBack, onSources, onFavoriteToggle, onRecalculated }: Props) {
  const [busy, setBusy] = useState(false);
  const [busyFeedback, setBusyFeedback] = useState<FeedbackCategory | null>(null);
  const [expandedSegmentId, setExpandedSegmentId] = useState<string | null>(null);
  const costPresentation = buildRouteCostPresentation(plan.segments, plan.cost_breakdown);
  const redirectPresentation = buildOfficialRedirectPresentation(plan);

  async function applyOption(segment: Segment, changeType: RecalculateChangeType, optionId: string, label: string) {
    setBusy(true);
    try {
      const result = await recalculate(
        plan.plan_id,
        segment.segment_id,
        changeType,
        optionId,
        label,
        changeType === "SEAT_TYPE" ? "FULL_REEVALUATION" : "PLAN_AND_RECOMMENDATION",
        changeType === "SEAT_TYPE" ? "RESULT_SET" : "TARGET_PLAN"
      );
      onRecalculated(result);
      Alert.alert("已更新路线", `${result.change_summary.message} ${result.change_summary.cost_delta.display_text}`);
    } catch (error) {
      Alert.alert("调整失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function openRedirect() {
    setBusy(true);
    try {
      const result = await bookingRedirect(plan.plan_id, redirectPresentation.segmentId, redirectPresentation.redirectType);
      void trackEvent({ eventType: "REDIRECT_CLICK", requestId: response.request_id, traceId: response.trace_id, planId: plan.plan_id, metadata: { redirectType: redirectPresentation.redirectType } }).catch(() => undefined);
      if (result.redirect.url_available && result.redirect.url) {
        const opened = await openExternalUrl(result.redirect.url);
        if (!opened.opened) Alert.alert("请手动确认", result.redirect.fallback_instruction ?? opened.message ?? "请打开对应官方平台确认。");
      } else {
        Alert.alert("请手动确认", result.redirect.fallback_instruction ?? "请打开对应官方平台确认。");
      }
    } catch (error) {
      Alert.alert("跳转失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function shareCurrentPlan() {
    try { await sharePlan(plan); } catch (error) { Alert.alert("分享失败", error instanceof Error ? error.message : "请稍后重试。"); }
  }

  async function copyCurrentPlan() {
    try {
      const copied = await copyPlanSummary(plan);
      Alert.alert(copied ? "已复制" : "无法直接复制", copied ? "行程摘要已复制。" : "当前平台没有剪贴板能力，可使用分享入口。");
    } catch (error) { Alert.alert("复制失败", error instanceof Error ? error.message : "请稍后重试。"); }
  }

  async function sendFeedback(category: FeedbackCategory) {
    setBusyFeedback(category);
    try {
      const latestSource = [...plan.data_sources].sort((left, right) => new Date(right.fetched_at.datetime).getTime() - new Date(left.fetched_at.datetime).getTime())[0];
      const feedback = await submitFeedback({ requestId: response.request_id, traceId: response.trace_id, correlationId: response.correlation_id, planId: plan.plan_id, sourceId: latestSource?.source_id ?? null, category });
      void trackEvent({ eventType: "FEEDBACK_SUBMITTED", requestId: response.request_id, traceId: response.trace_id, planId: plan.plan_id, metadata: { category } }).catch(() => undefined);
      Alert.alert("已收到", `反馈编号 ${feedback.feedback_id}`);
    } catch (error) { Alert.alert("反馈失败", error instanceof Error ? error.message : "请稍后重试。"); }
    finally { setBusyFeedback(null); }
  }

  const departure = formatClockTime(plan.departure_time) ?? "待确认";
  const arrival = formatClockTime(plan.arrival_time) ?? "待确认";

  return (
    <View style={styles.page}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="返回方案总览" onPress={onBack} style={({ pressed }) => [styles.headerAction, pressed && styles.pressed]}><Text style={styles.headerActionText}>‹</Text></Pressable>
        <View style={styles.headerCopy}><Text accessibilityRole="header" style={styles.title}>路线详情</Text><Text style={styles.subtitle}>综合推荐</Text></View>
        <Pressable accessibilityRole="button" accessibilityLabel="分享当前路线" disabled={busy} onPress={shareCurrentPlan} style={({ pressed }) => [styles.headerAction, pressed && styles.pressed]}><Text style={styles.headerActionText}>↗</Text></Pressable>
      </View>

      <View style={styles.summary}>
        <View style={styles.routeLineRow}>
          <Text numberOfLines={2} style={styles.routeEnd}>{response.travel_request.origin_text || "起点"}</Text>
          <View style={styles.routeLine}><View style={styles.routeNodeLeft} /><View style={styles.routeNodeRight} /></View>
          <Text numberOfLines={2} style={[styles.routeEnd, styles.routeEndRight]}>{response.travel_request.destination_text || "终点"}</Text>
        </View>
        <View style={styles.metrics}>
          <View style={styles.metric}><Text style={styles.metricLabel}>出发</Text><Text style={styles.metricValue}>{departure}</Text></View>
          <View style={styles.metric}><Text style={styles.metricLabel}>抵达</Text><Text style={styles.metricValue}>{arrival}</Text></View>
          <View style={styles.metric}><Text style={styles.metricLabel}>预计总价</Text><Text numberOfLines={1} style={styles.metricValue}>{formatMoney(plan.cost_breakdown.total_cost)}</Text></View>
        </View>
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHead}><Text accessibilityRole="header" style={styles.sectionTitle}>分段路线</Text><Text style={styles.sectionMeta}>{plan.segments.length} 段 · {minutesToText(plan.total_duration_minutes)}</Text></View>
        <View style={styles.journey}>
          {plan.segments.map((segment, index) => (
            <JourneyLegCard
              busy={busy}
              expanded={expandedSegmentId === segment.segment_id}
              key={segment.segment_id}
              last={index === plan.segments.length - 1}
              onApply={applyOption}
              onToggle={() => setExpandedSegmentId((current) => current === segment.segment_id ? null : segment.segment_id)}
              price={costPresentation.segmentPrices[segment.segment_id] ?? null}
              segment={segment}
            />
          ))}
          <JourneyCostSummary presentation={costPresentation} />
        </View>
        <Text style={styles.sourceNote}>票价与班次以对应官方渠道最终确认结果为准。</Text>
      </View>

      {plan.ticket_enhancement ? <View style={styles.ticket}><Text style={styles.ticketTitle}>票源增强 · {plan.ticket_enhancement.grade}</Text><Text style={styles.body}>{plan.ticket_enhancement.recommendation_message}</Text><Text style={styles.meta}>额外成本 {formatMoney(plan.ticket_enhancement.extra_cost)}，跳转后请按官方规则确认。</Text></View> : null}

      <View style={styles.actionGrid}>
        <Pressable accessibilityRole="button" accessibilityLabel={favorite ? "取消收藏当前方案" : "收藏当前方案"} disabled={busy} onPress={() => onFavoriteToggle(plan)} style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}><Text style={styles.secondaryActionText}>{favorite ? "已收藏" : "收藏"}</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="复制行程摘要" disabled={busy} onPress={copyCurrentPlan} style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}><Text style={styles.secondaryActionText}>复制摘要</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="查看数据来源" disabled={busy} onPress={onSources} style={({ pressed }) => [styles.secondaryAction, pressed && styles.pressed]}><Text style={styles.secondaryActionText}>数据来源</Text></Pressable>
      </View>

      <View>
        <Text accessibilityRole="header" style={styles.sectionTitle}>问题反馈</Text>
        <View style={styles.feedbackRow}>{FEEDBACK_OPTIONS.map((option) => <Pressable accessibilityRole="button" accessibilityLabel={`反馈${option.label}`} accessibilityState={{ disabled: busyFeedback !== null }} disabled={busyFeedback !== null} key={option.category} onPress={() => sendFeedback(option.category)} style={({ pressed }) => [styles.feedback, pressed && styles.pressed, busyFeedback !== null && styles.disabled]}><Text style={styles.feedbackText}>{busyFeedback === option.category ? "提交中" : option.label}</Text></Pressable>)}</View>
        <Text style={styles.meta}>反馈会关联当前方案和请求标识，不需要填写账号或支付信息。</Text>
      </View>

      <View style={styles.bottomAction}>
        <Text style={styles.redirectHelper}>{redirectPresentation.helperText}</Text>
        <Pressable
          accessibilityLabel={redirectPresentation.buttonLabel}
          accessibilityRole="button"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          onPress={openRedirect}
          style={({ pressed }) => [styles.primaryAction, pressed && !busy && styles.pressed, busy && styles.disabled]}
        >
          <Text style={styles.primaryActionText}>{busy ? "处理中" : redirectPresentation.buttonLabel}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: ui.spacing.lg, paddingBottom: ui.spacing.xl },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  headerCopy: { alignItems: "center", flex: 1 },
  headerAction: { alignItems: "center", backgroundColor: ui.colors.surface, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, minWidth: ui.touchTarget },
  headerActionText: { color: ui.colors.primaryDeep, fontSize: 22, fontWeight: "700" },
  title: { color: ui.colors.text, fontSize: 20, fontWeight: "800", lineHeight: 24 },
  subtitle: { color: ui.colors.textSecondary, fontSize: 11, marginTop: 2 },
  summary: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, padding: ui.spacing.lg },
  routeLineRow: { alignItems: "center", flexDirection: "row", gap: ui.spacing.sm },
  routeEnd: { color: ui.colors.text, flexShrink: 1, fontSize: 16, fontWeight: "800", lineHeight: 21, maxWidth: "36%" },
  routeEndRight: { textAlign: "right" },
  routeLine: { backgroundColor: ui.colors.primary, flex: 1, height: 2, position: "relative" },
  routeNodeLeft: { backgroundColor: ui.colors.surface, borderColor: ui.colors.primary, borderRadius: ui.radius.pill, borderWidth: 2, height: 11, left: 0, position: "absolute", top: -5, width: 11 },
  routeNodeRight: { backgroundColor: ui.colors.surface, borderColor: ui.colors.primary, borderRadius: ui.radius.pill, borderWidth: 2, height: 11, position: "absolute", right: 0, top: -5, width: 11 },
  metrics: { flexDirection: "row", gap: ui.spacing.sm, marginTop: ui.spacing.lg },
  metric: { flex: 1 },
  metricLabel: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15 },
  metricValue: { color: ui.colors.text, fontSize: 15, fontWeight: "800", lineHeight: 20, marginTop: 2 },
  section: { gap: 0 },
  sectionHead: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", marginBottom: ui.spacing.sm },
  sectionMeta: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 16 },
  sectionTitle: { color: ui.colors.text, fontSize: 16, fontWeight: "800", lineHeight: 21, marginBottom: ui.spacing.sm },
  journey: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, overflow: "hidden" },
  sourceNote: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15, marginHorizontal: 2, marginTop: 10 },
  body: { color: ui.colors.text, flex: 1, fontSize: 13, lineHeight: 19 },
  cost: { color: ui.colors.text, fontSize: 13, fontWeight: "800", paddingLeft: ui.spacing.md },
  ticket: { backgroundColor: ui.colors.warningSurface, borderRadius: ui.radius.card, gap: ui.spacing.xs, padding: ui.spacing.md },
  ticketTitle: { color: ui.colors.warning, fontSize: 14, fontWeight: "800" },
  meta: { color: ui.colors.textSecondary, fontSize: 12, lineHeight: 18, marginTop: ui.spacing.xs },
  actionGrid: { flexDirection: "row", flexWrap: "wrap", gap: ui.spacing.sm },
  secondaryAction: { alignItems: "center", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, minWidth: 96, paddingHorizontal: ui.spacing.md },
  secondaryActionText: { color: ui.colors.primaryDeep, fontSize: 13, fontWeight: "800" },
  bottomAction: { borderTopColor: ui.colors.line, borderTopWidth: StyleSheet.hairlineWidth, marginHorizontal: -ui.spacing.lg, paddingHorizontal: ui.spacing.lg, paddingTop: ui.spacing.md },
  redirectHelper: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15, marginBottom: ui.spacing.sm, textAlign: "center" },
  primaryAction: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.lg },
  primaryActionText: { color: ui.colors.surface, fontSize: 14, fontWeight: "800" },
  feedbackRow: { flexDirection: "row", flexWrap: "wrap", gap: ui.spacing.sm },
  feedback: { alignItems: "center", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  feedbackText: { color: ui.colors.primaryDeep, fontSize: 13, fontWeight: "700" },
  pressed: { opacity: 0.78, transform: [{ scale: 0.98 }] },
  disabled: { backgroundColor: ui.colors.disabled }
});
