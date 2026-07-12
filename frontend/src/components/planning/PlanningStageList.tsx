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
          <View accessibilityRole="summary" key={stage.label} style={[styles.stage, active && styles.stageActive]}>
            <Text style={[styles.status, (complete || active) && styles.statusActive]}>{complete ? "完成" : active ? "进行中" : "待处理"}</Text>
            <Text numberOfLines={1} style={[styles.label, (complete || active) && styles.labelActive]}>{stage.label}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { flexDirection: "row", gap: ui.spacing.xs },
  stage: { backgroundColor: "rgba(255,255,255,0.68)", borderRadius: ui.radius.control, flex: 1, minHeight: 58, minWidth: 0, paddingHorizontal: ui.spacing.sm, paddingVertical: ui.spacing.sm },
  stageActive: { backgroundColor: ui.colors.primarySoft },
  status: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 14 },
  statusActive: { color: ui.colors.primary },
  label: { color: ui.colors.textSecondary, fontSize: 11, fontWeight: "700", lineHeight: 16, marginTop: 2 },
  labelActive: { color: ui.colors.text, fontWeight: "800" }
});
