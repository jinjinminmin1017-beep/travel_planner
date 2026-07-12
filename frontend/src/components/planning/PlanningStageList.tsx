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
            <Text style={styles.status}>{complete ? "完成" : active ? "进行中" : "待处理"}</Text>
            <Text numberOfLines={1} style={[styles.label, active && styles.labelActive]}>{stage.label}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { flexDirection: "row", gap: ui.spacing.xs, marginTop: 14 },
  stage: { backgroundColor: "rgba(255,255,255,0.72)", borderRadius: ui.radius.control, flex: 1, minWidth: 0, paddingHorizontal: ui.spacing.sm, paddingVertical: 10 },
  stageActive: { backgroundColor: ui.colors.primarySoft },
  status: { color: ui.colors.planningStageText, fontSize: 10, lineHeight: 13.5 },
  label: { color: ui.colors.planningStageStrong, fontSize: 11, fontWeight: "700", lineHeight: 14.85, marginTop: 4 },
  labelActive: { color: ui.colors.primaryDeep, fontWeight: "800" }
});
