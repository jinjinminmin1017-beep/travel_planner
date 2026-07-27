import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan, TravelRequest } from "../../types";
import { buildCompactRouteTitle, latestPlanUpdatedAt } from "../../utils/routePlanning";
import { formatClockTime } from "./presentation";

type Props = { request: TravelRequest; plan: TravelPlan; planCount: number; onSources: () => void };

function formatUpdatedAt(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })
    .format(date)
    .replace(/^24:/, "00:");
}

export function ResultsHeader({ request, plan, planCount, onSources }: Props) {
  const departure = formatClockTime(plan.departure_time);
  const updatedAt = formatUpdatedAt(latestPlanUpdatedAt(plan));
  return (
    <View>
      <View style={styles.header}>
        <View style={styles.copy}>
          <Text accessibilityRole="header" numberOfLines={1} style={styles.title}>{buildCompactRouteTitle(request)}</Text>
          <Text style={styles.meta}>{request.travel_date}{departure ? ` · ${departure} 出发` : " · 出发时间待确认"}</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="更多操作与数据来源" hitSlop={ui.hitSlop} onPress={onSources} style={({ pressed }) => [styles.action, pressed && styles.pressed]}>
          <Text style={styles.actionText}>•••</Text>
        </Pressable>
      </View>
      <View style={styles.resultIntro}>
        <Text style={styles.resultCount}>已找到 {planCount} 种可行路线</Text>
        {updatedAt ? <Text style={styles.updatedAt}>更新于 {updatedAt}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", minHeight: 64 },
  copy: { flex: 1, minWidth: 0, paddingRight: ui.spacing.sm },
  title: { color: ui.colors.text, fontSize: 20, fontWeight: "800", lineHeight: 24 },
  meta: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15, marginTop: 3 },
  action: { alignItems: "center", backgroundColor: ui.colors.surface, borderRadius: ui.radius.control, flexShrink: 0, justifyContent: "center", minHeight: ui.touchTarget, minWidth: ui.touchTarget },
  actionText: { color: ui.colors.primaryDeep, fontSize: 15, fontWeight: "800", letterSpacing: 1 },
  resultIntro: { alignItems: "baseline", flexDirection: "row", justifyContent: "space-between", marginBottom: 10, marginTop: ui.spacing.xxs },
  resultCount: { color: ui.colors.text, flex: 1, fontSize: 15, fontWeight: "800", lineHeight: 21 },
  updatedAt: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15, marginLeft: ui.spacing.md },
  pressed: { opacity: 0.72, transform: [{ scale: 0.98 }] }
});
