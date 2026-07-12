import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { TimelinePoint } from "../../utils/routePlanning";
import { minutesToText } from "../../utils/format";
import { formatClockTime, segmentEndpoints, selectedOptionLabel } from "./presentation";

export function RouteTimelineItem({ item, last }: { item: TimelinePoint; last: boolean }) {
  const endpoints = segmentEndpoints(item.segment);
  const departure = formatClockTime(item.departureTime);
  const arrival = formatClockTime(item.arrivalTime);
  const option = selectedOptionLabel(item.segment);
  return (
    <View style={styles.row}>
      <View style={styles.rail}>
        <View style={styles.dot} />
        {!last ? <View style={styles.line} /> : null}
      </View>
      <View style={styles.content}>
        <View style={styles.topline}>
          <Text style={styles.time}>{departure ? `${item.departureIsEstimated ? "预计 " : ""}${departure}` : "时间待确认"}</Text>
          <Text style={styles.duration}>{minutesToText(item.segment.duration_minutes)}</Text>
        </View>
        <Text style={styles.title}>{endpoints.origin} → {endpoints.destination}</Text>
        <Text style={styles.meta}>{option ? `${option} · ` : ""}{arrival ? `${item.arrivalIsEstimated ? "预计 " : ""}${arrival} 到达` : "到达时间待确认"}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", minHeight: 70 },
  rail: { alignItems: "center", width: 24 },
  dot: { backgroundColor: ui.colors.surface, borderColor: ui.colors.primary, borderRadius: ui.radius.pill, borderWidth: 3, height: 13, marginTop: 3, width: 13, zIndex: 1 },
  line: { backgroundColor: ui.colors.connection, bottom: 0, position: "absolute", top: 17, width: 2 },
  content: { flex: 1, paddingBottom: ui.spacing.md, paddingLeft: ui.spacing.sm },
  topline: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  time: { color: ui.colors.primaryDeep, fontSize: 13, fontWeight: "800" },
  duration: { color: ui.colors.textSecondary, fontSize: 11 },
  title: { color: ui.colors.text, fontSize: 13, fontWeight: "800", lineHeight: 18, marginTop: ui.spacing.xs },
  meta: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 16, marginTop: 2 }
});
