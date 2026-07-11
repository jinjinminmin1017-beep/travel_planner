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
      <Text style={styles.title}>{partial ? "当前为部分结果" : "为什么推荐这条路线"}</Text>
      <Text style={styles.body}>{reason || comparisons.join("；") || "这条路线基于当前可用数据生成，建议在跳转后再次确认票价与时刻。"}</Text>
      {reason && comparisons.length ? <Text style={styles.meta}>{comparisons.join("；")}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  notice: { backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.card, padding: ui.spacing.md },
  partial: { backgroundColor: ui.colors.warningSurface },
  title: { color: ui.colors.text, fontSize: 14, fontWeight: "800", lineHeight: 19 },
  body: { color: ui.colors.text, fontSize: 13, lineHeight: 19, marginTop: ui.spacing.xs },
  meta: { color: ui.colors.textSecondary, fontSize: 12, lineHeight: 18, marginTop: ui.spacing.xs }
});
