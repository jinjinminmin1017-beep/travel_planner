import type { ImageSourcePropType } from "react-native";
import { ImageBackground, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan, TravelRequest } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";
import { countTransfers } from "../../utils/routePlanning";

type Props = { request: TravelRequest; plan: TravelPlan; imageSource?: ImageSourcePropType; destinationName?: string };

export function RouteSummaryHero({ request, plan, imageSource, destinationName }: Props) {
  const resolvedDestinationName = destinationName && destinationName !== "目的地" ? destinationName : request.destination_text;
  const content = (
    <View style={styles.overlay}>
      <Text style={styles.destination}>{resolvedDestinationName || "目的地待确认"}</Text>
      <Text style={styles.route}>{request.origin_text || "起点"} → {request.destination_text || "终点"}</Text>
      <View style={styles.metrics}>
        <View style={styles.primaryMetric}><Text numberOfLines={1} style={styles.metricLabel}>预计总价</Text><Text numberOfLines={1} style={styles.metricValue}>{formatMoney(plan.cost_breakdown.total_cost)}</Text></View>
        <View style={styles.metric}><Text numberOfLines={1} style={styles.metricLabel}>总耗时</Text><Text numberOfLines={1} style={styles.metricValue}>{minutesToText(plan.total_duration_minutes)}</Text></View>
        <View style={styles.metric}><Text numberOfLines={1} style={styles.metricLabel}>换乘</Text><Text numberOfLines={1} style={styles.metricValue}>{countTransfers(plan.segments)} 次</Text></View>
      </View>
    </View>
  );
  return imageSource ? <ImageBackground source={imageSource} imageStyle={styles.image} style={styles.hero}>{content}</ImageBackground> : <View style={[styles.hero, styles.fallback]}>{content}</View>;
}

const styles = StyleSheet.create({
  hero: { borderRadius: ui.radius.card, minHeight: 190, overflow: "hidden" },
  image: { borderRadius: ui.radius.card },
  fallback: { backgroundColor: ui.colors.primaryDeep },
  overlay: { backgroundColor: "rgba(8, 28, 31, 0.54)", flex: 1, justifyContent: "flex-end", padding: ui.spacing.lg },
  destination: { color: ui.colors.surface, fontSize: 25, fontWeight: "800", lineHeight: 30 },
  route: { color: ui.colors.onPrimaryMuted, fontSize: 13, lineHeight: 19, marginTop: ui.spacing.xs },
  metrics: { alignItems: "stretch", flexDirection: "row", marginTop: ui.spacing.lg },
  primaryMetric: { flex: 1.25, minWidth: 0 },
  metric: { borderLeftColor: "rgba(255,255,255,0.34)", borderLeftWidth: StyleSheet.hairlineWidth, flex: 1, minWidth: 0, paddingLeft: ui.spacing.sm },
  metricLabel: { color: ui.colors.onPrimaryMuted, fontSize: 11, lineHeight: 16 },
  metricValue: { color: ui.colors.surface, fontSize: 15, fontWeight: "800", lineHeight: 20, marginTop: 2 }
});
