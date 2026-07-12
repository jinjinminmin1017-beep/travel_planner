import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan } from "../../types";
import { buildRouteTimeline } from "../../utils/routePlanning";
import { RouteTimelineItem } from "./RouteTimelineItem";

export function RouteTimeline({ plan }: { plan: TravelPlan }) {
  const timeline = buildRouteTimeline(plan);
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.heading}>行程时间轴</Text>
      <View style={styles.timeline}>
        {timeline.length ? timeline.map((item, index) => <RouteTimelineItem item={item} key={item.segment.segment_id} last={index === timeline.length - 1} />) : <Text style={styles.empty}>当前方案暂缺分段路线。</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: ui.spacing.xxs },
  heading: { color: ui.colors.text, fontSize: 16, fontWeight: "800", lineHeight: 21, marginBottom: ui.spacing.sm },
  timeline: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, paddingHorizontal: ui.spacing.md, paddingTop: ui.spacing.md },
  empty: { color: ui.colors.textSecondary, fontSize: 13, lineHeight: 19 }
});
