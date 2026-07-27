import { StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import { buildPlanningStagePresentation } from "../../utils/routePlanning";

export function PlanningStageList({ progress }: { progress: number }) {
  const presentation = buildPlanningStagePresentation(progress);

  return (
    <View accessibilityLabel={`规划进度${Math.round(progress)}%，${presentation.currentTask}`} accessibilityRole="list" style={styles.list}>
      {presentation.stages.map((stage) => {
        const complete = stage.status === "COMPLETE";
        const active = stage.status === "ACTIVE";
        return (
          <View accessibilityRole="summary" key={stage.label} style={styles.stage}>
            <View style={[styles.node, complete && styles.nodeComplete, active && styles.nodeActive]} />
            <Text style={[styles.label, active && styles.labelActive]}>{stage.label}</Text>
            <Text style={[styles.status, active && styles.statusActive]}>{complete ? "已完成" : active ? "进行中" : "待处理"}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, marginTop: 14, paddingHorizontal: ui.spacing.md },
  stage: { alignItems: "center", borderBottomColor: ui.colors.line, borderBottomWidth: StyleSheet.hairlineWidth, flexDirection: "row", gap: 10, minHeight: 52 },
  node: { backgroundColor: ui.colors.surface, borderColor: ui.colors.line, borderRadius: ui.radius.pill, borderWidth: 2, height: 16, width: 16 },
  nodeComplete: { backgroundColor: ui.colors.surface, borderColor: ui.colors.primary, borderWidth: 5 },
  nodeActive: { backgroundColor: ui.colors.connection, borderColor: ui.colors.primary },
  status: { color: ui.colors.planningStageText, fontSize: 10, lineHeight: 15 },
  statusActive: { color: ui.colors.primaryDeep, fontWeight: "800" },
  label: { color: ui.colors.planningStageStrong, flex: 1, fontSize: 12, fontWeight: "700", lineHeight: 18 },
  labelActive: { color: ui.colors.primaryDeep, fontWeight: "800" }
});
