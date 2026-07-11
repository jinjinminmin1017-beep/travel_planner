import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";

const STAGES = [
  { label: "需求解析", threshold: 0 },
  { label: "地点确认", threshold: 21 },
  { label: "车次比对", threshold: 41 },
  { label: "方案评分", threshold: 76 }
] as const;

export function PlanningStageList({ progress }: { progress: number }) {
  const activeIndex = progress >= 100 ? STAGES.length : STAGES.reduce((latest, stage, index) => progress >= stage.threshold ? index : latest, 0);

  return (
    <View accessibilityRole="list" style={styles.list}>
      {STAGES.map((stage, index) => {
        const complete = progress >= 100 || index < activeIndex;
        const active = progress < 100 && index === activeIndex;
        return (
          <View accessibilityRole="summary" key={stage.label} style={styles.row}>
            <View style={[styles.marker, complete && styles.markerComplete, active && styles.markerActive]}>
              <Text style={[styles.markerText, (complete || active) && styles.markerTextActive]}>{complete ? "✓" : index + 1}</Text>
            </View>
            <Text style={[styles.label, (complete || active) && styles.labelActive]}>{stage.label}</Text>
            <Text style={styles.status}>{complete ? "已完成" : active ? "处理中" : "等待"}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: ui.spacing.sm },
  row: { alignItems: "center", flexDirection: "row", minHeight: ui.touchTarget },
  marker: { alignItems: "center", backgroundColor: ui.colors.disabled, borderRadius: ui.radius.pill, height: 28, justifyContent: "center", width: 28 },
  markerActive: { backgroundColor: ui.colors.primarySoft },
  markerComplete: { backgroundColor: ui.colors.primary },
  markerText: { color: ui.colors.disabledText, fontSize: 12, fontWeight: "800" },
  markerTextActive: { color: ui.colors.primaryDeep },
  label: { color: ui.colors.textSecondary, flex: 1, fontSize: 14, fontWeight: "600", marginLeft: ui.spacing.md },
  labelActive: { color: ui.colors.text, fontWeight: "800" },
  status: { color: ui.colors.textSecondary, fontSize: 12 }
});
