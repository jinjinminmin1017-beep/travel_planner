import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan, TravelRequest } from "../../types";
import { buildRouteTitle } from "../../utils/routePlanning";
import { formatClockTime } from "./presentation";

type Props = { request: TravelRequest; plan: TravelPlan; onSources: () => void };

export function ResultsHeader({ request, plan, onSources }: Props) {
  const departure = formatClockTime(plan.departure_time);
  return (
    <View style={styles.header}>
      <View style={styles.copy}>
        <Text accessibilityRole="header" style={styles.title}>{buildRouteTitle(request)}</Text>
        <Text style={styles.meta}>{request.travel_date}{departure ? ` · ${departure} 出发` : " · 出发时间待确认"}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel="查看数据来源" hitSlop={ui.hitSlop} onPress={onSources} style={({ pressed }) => [styles.action, pressed && styles.pressed]}>
        <Text style={styles.actionText}>•••</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", marginBottom: ui.spacing.md },
  copy: { flex: 1, minWidth: 0, paddingRight: ui.spacing.sm },
  title: { color: ui.colors.text, fontSize: 25, fontWeight: "800", lineHeight: 30 },
  meta: { color: ui.colors.textSecondary, fontSize: 12, lineHeight: 18, marginTop: ui.spacing.xs },
  action: { alignItems: "center", backgroundColor: ui.colors.surface, borderRadius: ui.radius.control, flexShrink: 0, justifyContent: "center", minHeight: ui.touchTarget, minWidth: ui.touchTarget },
  actionText: { color: ui.colors.primaryDeep, fontSize: 15, fontWeight: "800", letterSpacing: 1 },
  pressed: { opacity: 0.72, transform: [{ scale: 0.98 }] }
});
