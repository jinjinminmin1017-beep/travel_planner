import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan } from "../../types";
import { riskLabel } from "../../utils/format";

export function PlanRiskNotice({ plan }: { plan: TravelPlan }) {
  const items = plan.risk_assessment.risk_items;
  return (
    <View style={styles.notice}>
      <Text style={styles.title}>方案风险 · {riskLabel(plan.risk_assessment.overall_risk_level)}</Text>
      {items.length ? items.map((item) => <Text key={item.risk_id} style={styles.body}>{item.title}：{item.message}</Text>) : <Text style={styles.body}>当前没有记录到额外风险，票价与班次仍以外部官方平台为准。</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  notice: { backgroundColor: ui.colors.warningSurface, borderRadius: ui.radius.card, gap: ui.spacing.xs, padding: ui.spacing.md },
  title: { color: ui.colors.warning, fontSize: 14, fontWeight: "800", lineHeight: 19 },
  body: { color: ui.colors.text, fontSize: 12, lineHeight: 18 }
});
