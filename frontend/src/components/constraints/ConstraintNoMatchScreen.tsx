import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { ui } from "../../designSystem";
import type { RelaxationAlternative, TravelPlanResponse } from "../../types";
import { minutesToText } from "../../utils/format";

const CATEGORY_LABELS: Record<RelaxationAlternative["category"], string> = {
  CLOSEST_TO_TIME: "最接近期望时间",
  CLOSEST_TO_BUDGET: "最接近预算",
  LEAST_BEHAVIOR_CHANGE: "改动最少"
};

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
                    <Text style={styles.detailText}>数据完整度 {Math.round(alternative.plan.data_quality.completeness_score * 100)}%</Text>
                    <Text style={styles.detailText}>风险等级 {alternative.plan.risk_assessment.overall_risk_level}</Text>
                    <Text style={styles.detailText}>此处不提供购票入口；确认放宽后系统会重新规划。</Text>
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
  detailText: { color: "#526168", fontSize: 13, lineHeight: 19 },
  primaryButton: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: 8, minHeight: ui.touchTarget, justifyContent: "center", paddingHorizontal: 12 },
  primaryButtonText: { color: "#ffffff", fontSize: 14, fontWeight: "800" },
  secondaryButton: { alignItems: "center", borderColor: "#cbd8da", borderRadius: 8, borderWidth: 1, minHeight: ui.touchTarget, justifyContent: "center" },
  secondaryButtonText: { color: ui.colors.primary, fontSize: 14, fontWeight: "800" },
  editButton: { alignItems: "center", minHeight: ui.touchTarget, justifyContent: "center" },
  editButtonText: { color: ui.colors.primary, fontSize: 14, fontWeight: "800" },
  disabled: { opacity: 0.65 }
});
