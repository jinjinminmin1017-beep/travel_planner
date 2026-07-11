import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan } from "../../types";
import { buildRouteTimeline } from "../../utils/routePlanning";
import { RouteTimelineItem } from "./RouteTimelineItem";

export function RouteTimeline({ plan }: { plan: TravelPlan }) {
  const timeline = buildRouteTimeline(plan);
  return (
    <View>
      <Text accessibilityRole="header" style={styles.heading}>门到门路线</Text>
      {timeline.length ? timeline.map((item, index) => <RouteTimelineItem item={item} key={item.segment.segment_id} last={index === timeline.length - 1} />) : <Text style={styles.empty}>当前方案暂缺分段路线。</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  heading: { color: ui.colors.text, fontSize: 16, fontWeight: "800", lineHeight: 21, marginBottom: ui.spacing.md },
  empty: { color: ui.colors.textSecondary, fontSize: 13, lineHeight: 19 }
});
