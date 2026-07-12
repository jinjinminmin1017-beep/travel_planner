import type { ImageSourcePropType } from "react-native";
import { ImageBackground, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TravelPlan, TravelRequest } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";
import { countTransfers } from "../../utils/routePlanning";

type Props = { request: TravelRequest; plan: TravelPlan; imageSource?: ImageSourcePropType; destinationName?: string };

export function RouteSummaryHero({ request, plan, imageSource, destinationName }: Props) {
  const resolvedDestinationName = destinationName && destinationName !== "目的地" ? destinationName : request.destination_text;
  const heading = (
    <View style={styles.imageOverlay}>
      <View style={styles.routeHeading}>
        <Text style={styles.eyebrow}>综合推荐 · {resolvedDestinationName || "目的地"}</Text>
        <Text numberOfLines={2} style={styles.route}>{request.origin_text || "起点"} <Text style={styles.arrow}>→</Text> {request.destination_text || "终点"}</Text>
      </View>
    </View>
  );
  return (
    <View style={styles.hero}>
      {imageSource ? <ImageBackground source={imageSource} imageStyle={styles.image} style={styles.imageFrame}>{heading}</ImageBackground> : <View style={[styles.imageFrame, styles.fallback]}>{heading}</View>}
      <View style={styles.metrics}>
        <View style={styles.metric}><Text numberOfLines={1} style={styles.metricLabel}>预计总价</Text><Text adjustsFontSizeToFit minimumFontScale={0.78} numberOfLines={1} style={styles.metricValue}>{formatMoney(plan.cost_breakdown.total_cost)}</Text></View>
        <View style={[styles.metric, styles.durationMetric]}><Text numberOfLines={1} style={styles.metricLabel}>全程耗时</Text><Text adjustsFontSizeToFit minimumFontScale={0.78} numberOfLines={1} style={styles.metricValue}>{minutesToText(plan.total_duration_minutes)}</Text></View>
        <View style={[styles.metric, styles.transferMetric]}><Text numberOfLines={1} style={styles.metricLabel}>换乘</Text><Text adjustsFontSizeToFit minimumFontScale={0.78} numberOfLines={1} style={styles.metricValue}>{countTransfers(plan.segments)} 次</Text></View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { backgroundColor: ui.colors.primaryDeep, borderRadius: ui.radius.card, overflow: "hidden" },
  imageFrame: { height: 116 },
  image: { borderTopLeftRadius: ui.radius.card, borderTopRightRadius: ui.radius.card },
  fallback: { backgroundColor: ui.colors.primaryDeep },
  imageOverlay: { backgroundColor: "rgba(7,36,40,0.42)", flex: 1, justifyContent: "flex-end", padding: ui.spacing.lg },
  routeHeading: { maxWidth: "96%" },
  eyebrow: { color: ui.colors.onPrimaryMuted, fontSize: 11, fontWeight: "700", lineHeight: 16 },
  route: { color: ui.colors.surface, fontSize: 24, fontWeight: "800", letterSpacing: -0.5, lineHeight: 29, marginTop: 2 },
  arrow: { color: ui.colors.connection },
  metrics: { alignItems: "stretch", backgroundColor: "rgba(255,255,255,0.12)", flexDirection: "row", gap: 1 },
  metric: { backgroundColor: ui.colors.primaryDeep, flex: 1, minHeight: 64, minWidth: 0, paddingHorizontal: 10, paddingVertical: ui.spacing.md },
  durationMetric: { flex: 1.25 },
  transferMetric: { flex: 0.75 },
  metricLabel: { color: ui.colors.onPrimaryMuted, fontSize: 11, lineHeight: 16 },
  metricValue: { color: ui.colors.surface, fontSize: 14, fontWeight: "800", letterSpacing: -0.2, lineHeight: 18, marginTop: 3 }
});
