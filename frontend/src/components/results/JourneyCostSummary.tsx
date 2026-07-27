import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import { formatMoney } from "../../utils/format";
import type { RouteCostPresentation } from "../../utils/routePlanning";

export function JourneyCostSummary({
  presentation
}: {
  presentation: RouteCostPresentation;
}) {
  return (
    <>
      {presentation.otherCosts.map((item) => (
        <View key={`${item.label}-${item.amount.amount_minor}`} style={styles.otherCost}>
          <Text style={styles.otherLabel}>{item.label}</Text>
          <Text style={styles.otherValue}>{formatMoney(item.amount)} · 估算</Text>
        </View>
      ))}
      <View style={styles.total}>
        <View style={styles.totalCopy}>
          <Text style={styles.totalLabel}>路线费用合计</Text>
          <Text style={styles.totalMeta}>分段费用以官方渠道最终确认结果为准</Text>
        </View>
        <Text numberOfLines={1} style={styles.totalPrice}>{formatMoney(presentation.total)}</Text>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  otherCost: { alignItems: "center", borderTopColor: ui.colors.line, borderTopWidth: StyleSheet.hairlineWidth, flexDirection: "row", justifyContent: "space-between", marginLeft: 50, minHeight: 40, paddingRight: 14 },
  otherLabel: { color: ui.colors.textSecondary, flex: 1, fontSize: 11, lineHeight: 16 },
  otherValue: { color: ui.colors.text, flexShrink: 0, fontSize: 13, fontWeight: "800" },
  total: { alignItems: "center", backgroundColor: ui.colors.primarySoft, flexDirection: "row", gap: ui.spacing.lg, justifyContent: "space-between", marginTop: ui.spacing.sm, minHeight: 64, paddingBottom: 14, paddingLeft: 50, paddingRight: 14, paddingTop: 13 },
  totalCopy: { flex: 1, minWidth: 0 },
  totalLabel: { color: ui.colors.text, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  totalMeta: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15, marginTop: 2 },
  totalPrice: { color: ui.colors.primaryDeep, flexShrink: 0, fontSize: 20, fontWeight: "800", letterSpacing: -0.4, lineHeight: 24 }
});
