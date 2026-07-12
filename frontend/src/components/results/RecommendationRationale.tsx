import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { RecommendationSlot, TravelPlan } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";
import { calculatePlanDifference, findCheapestPlan, findFastestPlan, findRecommendationReason, moneyDelta } from "../../utils/routePlanning";

export function RecommendationRationale({ plan, plans, recommendations, partial }: { plan: TravelPlan; plans: TravelPlan[]; recommendations: RecommendationSlot[]; partial: boolean }) {
  const reason = findRecommendationReason(plan, recommendations);
  const cheapest = findCheapestPlan(plans);
  const fastest = findFastestPlan(plans);
  const comparisons: string[] = [];
  if (cheapest && cheapest.plan_id !== plan.plan_id) {
    const difference = calculatePlanDifference(plan, cheapest);
    comparisons.push(`比最低价方案高 ${formatMoney(moneyDelta(plan.cost_breakdown.total_cost, difference.costDeltaMinor))}`);
  }
  if (fastest && fastest.plan_id !== plan.plan_id) {
    const difference = calculatePlanDifference(plan, fastest);
    comparisons.push(`比最快方案多 ${minutesToText(Math.abs(difference.durationDeltaMinutes))}`);
  }

  return (
    <View style={[styles.notice, partial && styles.partial]}>
      <View style={[styles.mark, partial && styles.markPartial]}><Text style={styles.markText}>{partial ? "注" : "荐"}</Text></View>
      <View style={styles.copy}>
        <Text style={styles.body}><Text style={styles.title}>{partial ? "当前为部分结果：" : "为什么推荐："}</Text>{reason || comparisons.join("；") || "这条路线基于当前可用数据生成，建议在跳转后再次确认票价与时刻。"}</Text>
        {reason && comparisons.length ? <Text style={styles.meta}>{comparisons.join("；")}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  notice: { alignItems: "flex-start", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.card, flexDirection: "row", gap: ui.spacing.sm, padding: ui.spacing.md },
  partial: { backgroundColor: ui.colors.warningSurface },
  mark: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: ui.radius.small, height: 28, justifyContent: "center", width: 28 },
  markPartial: { backgroundColor: ui.colors.warning },
  markText: { color: ui.colors.surface, fontSize: 12, fontWeight: "800" },
  copy: { flex: 1 },
  title: { color: ui.colors.primaryDeep, fontWeight: "800" },
  body: { color: ui.colors.text, fontSize: 12, lineHeight: 18 },
  meta: { color: ui.colors.textSecondary, fontSize: 12, lineHeight: 18, marginTop: ui.spacing.xs }
});
