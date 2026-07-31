import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { ui } from "../../designSystem";
import type { ConstraintViolation, RelaxationAlternative, SourceFailure, TravelPlanResponse } from "../../types";
import { formatMoney, minutesToText, riskLabel } from "../../utils/format";
import { formatClockTime, segmentTitle, selectedOptionLabel } from "../results/presentation";

const CATEGORY_LABELS: Record<RelaxationAlternative["category"], string> = {
  CLOSEST_TO_TIME: "最接近期望时间",
  CLOSEST_TO_BUDGET: "最接近预算",
  LEAST_BEHAVIOR_CHANGE: "改动最少"
};

const ENHANCED_NO_MATCH_DETAIL_ENABLED = process.env.EXPO_PUBLIC_ENHANCED_NO_MATCH_DETAIL_ENABLED !== "false";

const CONSTRAINT_LABELS: Record<string, string> = {
  LATEST_ARRIVAL: "最晚到达",
  EARLIEST_DEPARTURE: "最早出发",
  ARRIVAL_TIME_WINDOW: "到达时间窗",
  DEPARTURE_TIME_WINDOW: "出发时间窗",
  MAX_TOTAL_COST: "总预算",
  ALLOWED_TRANSPORT_MODES: "允许的交通方式",
  EXCLUDED_TRANSPORT_MODES: "排除的交通方式",
  PREFERRED_RAIL_SEAT: "铁路席别",
  PREFERRED_FLIGHT_CABIN: "航班舱位"
};

function constraintValue(value: Record<string, unknown>) {
  if (typeof value.datetime === "string") return value.datetime.replace("T", " ");
  if (typeof value.amount_minor === "number" && typeof value.currency === "string" && typeof value.scale === "number") {
    return formatMoney({ amount_minor: value.amount_minor, currency: value.currency, scale: value.scale, display_text: null, is_estimated: false });
  }
  if (Array.isArray(value.modes)) return value.modes.join("、");
  if (Array.isArray(value.excluded_modes)) return value.excluded_modes.join("、");
  if (typeof value.value === "string") return value.value;
  return "以原始需求为准";
}

function deviationText(violation: ConstraintViolation) {
  const deviation = violation.deviation;
  if (deviation.kind === "DURATION") return `${deviation.value} 分钟（${deviation.direction === "LATER" ? "更晚" : "更早"}）`;
  if (deviation.kind === "MONEY") return formatMoney({ ...deviation, display_text: null, is_estimated: false });
  if (deviation.kind === "CATEGORICAL") return `${deviation.requested} → ${deviation.actual}`;
  return [...deviation.added_modes, ...deviation.removed_modes].join("、") || "交通方式有变化";
}

function airlineLabel(sourceId: string) {
  const labels: Array<[string, string]> = [
    ["airline_hu", "海南航空"], ["airline_9c", "春秋航空"], ["airline_qw", "青岛航空"],
    ["airline_mu", "中国东方航空"], ["airline_cz", "中国南方航空"], ["airline_ca", "中国国际航空"],
    ["airline_zh", "深圳航空"], ["airline_ho", "吉祥航空"], ["airline_sc", "山东航空"]
  ];
  return labels.find(([marker]) => sourceId.toLowerCase().includes(marker))?.[1] ?? sourceId;
}

function airlineOutcome(failure: SourceFailure) {
  const code = (failure.error_code ?? "").toUpperCase();
  if (code.endsWith("_EMPTY")) return "有效查询，无可验证班次";
  if (code.includes("PARSER") || code.includes("INVALID_RESPONSE")) return "响应结构暂不支持";
  if (code.includes("TIMEOUT")) return "查询超时";
  if (code.includes("RATE_LIMIT")) return "查询受限";
  if (code.includes("DISABLED")) return "当前未启用";
  return "查询失败";
}

export function ConstraintNoMatchScreen({
  busy,
  response,
  onConfirm,
  onEdit
}: {
  busy: boolean;
  response: TravelPlanResponse;
  onConfirm: (alternative: RelaxationAlternative) => void;
  onEdit: () => void;
}) {
  const analysis = response.constraint_analysis;
  const [expandedId, setExpandedId] = useState<string | null>(null);
  if (!analysis) return null;
  return (
    <View style={styles.page}>
      <Text style={styles.kicker}>约束未满足</Text>
      <Text style={styles.title}>这次没有完全匹配的方案</Text>
      <Text style={styles.summary}>{analysis.summary}</Text>

      <View style={styles.coveragePanel}>
        <Text style={styles.sectionTitle}>查询覆盖</Text>
        {analysis.coverage.map((item) => (
          <View key={item.transport_mode} style={styles.coverageRow}>
            <Text style={styles.coverageMode}>{item.transport_mode === "RAIL" ? "铁路" : item.transport_mode === "FLIGHT" ? "航班" : item.transport_mode}</Text>
            <Text style={styles.coverageMessage}>{item.message}</Text>
          </View>
        ))}
      </View>

      {response.source_failures.some((failure) => failure.source_id.toLowerCase().includes("airline") || failure.source_id.toLowerCase().includes("flight")) ? (
        <View style={styles.coveragePanel}>
          <Text style={styles.sectionTitle}>航司查询说明</Text>
          {response.source_failures
            .filter((failure) => failure.source_id.toLowerCase().includes("airline") || failure.source_id.toLowerCase().includes("flight"))
            .map((failure) => (
              <View key={failure.failure_id} style={styles.coverageRow}>
                <Text style={styles.coverageMode}>{airlineLabel(failure.source_id)} · {airlineOutcome(failure)}</Text>
                <Text style={styles.coverageMessage}>{failure.user_visible_message}</Text>
              </View>
            ))}
        </View>
      ) : null}

      {analysis.alternatives.length ? (
        <View style={styles.alternativeList}>
          <Text style={styles.sectionTitle}>需确认放宽的备选</Text>
          {analysis.alternatives.map((alternative) => {
            const expanded = expandedId === alternative.alternative_id;
            return (
              <View key={alternative.alternative_id} style={styles.card}>
                <Text style={styles.warningBadge}>不满足原始要求</Text>
                <Text style={styles.category}>{CATEGORY_LABELS[alternative.category]}</Text>
                <Text style={styles.planName}>{alternative.plan.plan_name}</Text>
                <Text style={styles.planMeta}>
                  {alternative.plan.cost_breakdown.total_cost.display_text ?? "费用待确认"} · {minutesToText(alternative.plan.total_duration_minutes)}
                </Text>
                {alternative.violations.map((violation) => (
                  <Text key={`${alternative.alternative_id}-${violation.constraint_type}`} style={styles.violation}>{violation.user_visible_message}</Text>
                ))}
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ expanded }}
                  disabled={busy}
                  onPress={() => setExpandedId(expanded ? null : alternative.alternative_id)}
                  style={styles.secondaryButton}
                >
                  <Text style={styles.secondaryButtonText}>{expanded ? "收起详情" : "查看备选详情"}</Text>
                </Pressable>
                {expanded ? (
                  <View style={styles.details}>
                    {!ENHANCED_NO_MATCH_DETAIL_ENABLED ? (
                      <>
                        <Text style={styles.detailText}>数据完整度 {Math.round(alternative.plan.data_quality.completeness_score * 100)}%</Text>
                        <Text style={styles.confirmNotice}>此处不提供购票入口；确认放宽后系统会重新规划。</Text>
                      </>
                    ) : (
                      <>
                    <Text style={styles.detailHeading}>门到门概览</Text>
                    <Text style={styles.detailText}>
                      {formatClockTime(alternative.plan.departure_time) ?? "出发时间待确认"} → {formatClockTime(alternative.plan.arrival_time) ?? "到达时间待确认"}
                      {` · ${minutesToText(alternative.plan.total_duration_minutes)} · ${formatMoney(alternative.plan.cost_breakdown.total_cost)}`}
                    </Text>
                    <Text style={styles.detailHeading}>完整路线</Text>
                    {alternative.plan.segments.map((segment) => (
                      <View key={segment.segment_id} style={styles.segmentRow}>
                        <Text style={styles.segmentTitle}>{segmentTitle(segment)}</Text>
                        <Text style={styles.detailText}>
                          {formatClockTime(segment.departure_time) ?? "时间待确认"}–{formatClockTime(segment.arrival_time) ?? "时间待确认"}
                          {selectedOptionLabel(segment) ? ` · ${selectedOptionLabel(segment)}` : ""}
                        </Text>
                      </View>
                    ))}
                    <Text style={styles.detailHeading}>确认后将放宽的条件</Text>
                    {alternative.violations.map((violation) => (
                      <View key={`detail-${alternative.alternative_id}-${violation.constraint_type}`} style={styles.violationDetail}>
                        <Text style={styles.segmentTitle}>{CONSTRAINT_LABELS[violation.constraint_type] ?? violation.constraint_type}</Text>
                        <Text style={styles.detailText}>请求：{constraintValue(violation.requested_value)}</Text>
                        <Text style={styles.detailText}>实际：{constraintValue(violation.actual_value)} · 偏差：{deviationText(violation)}</Text>
                      </View>
                    ))}
                    <Text style={styles.detailHeading}>仍满足的条件</Text>
                    <Text style={styles.detailText}>{alternative.preserved_constraints.map((item) => CONSTRAINT_LABELS[item] ?? item).join("、") || "没有额外可确认的硬约束"}</Text>
                    <Text style={styles.detailHeading}>数据与风险</Text>
                    {alternative.plan.data_sources.map((source) => (
                      <Text key={source.source_id} style={styles.detailText}>
                        {source.source_name} · 更新于 {source.fetched_at.datetime.replace("T", " ")}
                      </Text>
                    ))}
                    <Text style={styles.detailText}>数据完整度 {Math.round(alternative.plan.data_quality.completeness_score * 100)}% · {riskLabel(alternative.plan.risk_assessment.overall_risk_level)}</Text>
                    {alternative.plan.risk_assessment.risk_items.map((risk) => <Text key={risk.risk_id} style={styles.detailText}>{risk.title}：{risk.message}</Text>)}
                    {alternative.plan.data_quality.missing_components.map((item) => <Text key={`missing-${item}`} style={styles.detailText}>缺口：{item}</Text>)}
                    {alternative.plan.data_quality.warnings.map((item) => <Text key={`warning-${item}`} style={styles.detailText}>提示：{item}</Text>)}
                    <Text style={styles.confirmNotice}>详情仅供确认放宽条件；此处不提供购票入口，确认后系统会按新条件重新规划。</Text>
                      </>
                    )}
                  </View>
                ) : null}
                <Pressable accessibilityRole="button" disabled={busy} onPress={() => onConfirm(alternative)} style={[styles.primaryButton, busy && styles.disabled]}>
                  <Text style={styles.primaryButtonText}>{busy ? "重新规划中" : "确认放宽并重新规划"}</Text>
                </Pressable>
              </View>
            );
          })}
        </View>
      ) : (
        <Text style={styles.summary}>当前没有可安全展示的备选，请修改时间、预算或交通方式要求。</Text>
      )}

      <Pressable accessibilityRole="button" disabled={busy} onPress={onEdit} style={styles.editButton}>
        <Text style={styles.editButtonText}>修改原始需求</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: 12 },
  kicker: { color: ui.colors.primary, fontSize: 12, fontWeight: "800" },
  title: { color: "#172126", fontSize: 24, fontWeight: "800" },
  summary: { color: "#526168", fontSize: 15, lineHeight: 22 },
  sectionTitle: { color: "#172126", fontSize: 17, fontWeight: "800" },
  coveragePanel: { backgroundColor: "#f2f6f7", borderRadius: 8, gap: 8, padding: 14 },
  coverageRow: { gap: 2 },
  coverageMode: { color: "#172126", fontSize: 14, fontWeight: "800" },
  coverageMessage: { color: "#66747c", fontSize: 13, lineHeight: 19 },
  alternativeList: { gap: 10 },
  card: { backgroundColor: "#ffffff", borderColor: "#e5c79b", borderRadius: 8, borderWidth: 1, gap: 8, padding: 14 },
  warningBadge: { alignSelf: "flex-start", backgroundColor: "#fff1dc", borderRadius: 999, color: "#8a4c00", fontSize: 12, fontWeight: "800", overflow: "hidden", paddingHorizontal: 8, paddingVertical: 4 },
  category: { color: ui.colors.primary, fontSize: 12, fontWeight: "800" },
  planName: { color: "#172126", fontSize: 18, fontWeight: "800" },
  planMeta: { color: "#526168", fontSize: 14 },
  violation: { color: "#8a4c00", fontSize: 14, lineHeight: 20 },
  details: { backgroundColor: "#f7f9f9", borderRadius: 8, gap: 4, padding: 10 },
  detailHeading: { color: "#172126", fontSize: 13, fontWeight: "800", marginTop: 6 },
  detailText: { color: "#526168", fontSize: 13, lineHeight: 19 },
  segmentRow: { borderBottomColor: "#e6ecec", borderBottomWidth: 1, gap: 2, paddingVertical: 6 },
  segmentTitle: { color: "#26363d", fontSize: 13, fontWeight: "700", lineHeight: 19 },
  violationDetail: { backgroundColor: "#fff8ed", borderRadius: 6, gap: 2, padding: 8 },
  confirmNotice: { color: "#8a4c00", fontSize: 13, fontWeight: "700", lineHeight: 19, marginTop: 6 },
  primaryButton: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: 8, minHeight: ui.touchTarget, justifyContent: "center", paddingHorizontal: 12 },
  primaryButtonText: { color: "#ffffff", fontSize: 14, fontWeight: "800" },
  secondaryButton: { alignItems: "center", borderColor: "#cbd8da", borderRadius: 8, borderWidth: 1, minHeight: ui.touchTarget, justifyContent: "center" },
  secondaryButtonText: { color: ui.colors.primary, fontSize: 14, fontWeight: "800" },
  editButton: { alignItems: "center", minHeight: ui.touchTarget, justifyContent: "center" },
  editButtonText: { color: ui.colors.primary, fontSize: 14, fontWeight: "800" },
  disabled: { opacity: 0.65 }
});
