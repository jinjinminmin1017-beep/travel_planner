import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { RecommendationSlot, TravelPlan } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";

const SLOT_ORDER: RecommendationSlot["recommendation_type"][] = ["BALANCED", "MOST_COMFORTABLE", "CHEAPEST"];
const LABELS: Record<RecommendationSlot["recommendation_type"], string> = { BALANCED: "综合推荐", MOST_COMFORTABLE: "更舒适", CHEAPEST: "更省预算" };

type Props = { recommendations: RecommendationSlot[]; plans: TravelPlan[]; selectedPlanId: string; onSelect: (plan: TravelPlan, slot: RecommendationSlot) => void };

export function PlanSelector({ recommendations, plans, selectedPlanId, onSelect }: Props) {
  return (
    <View accessibilityRole="tablist" style={styles.selector}>
      {SLOT_ORDER.map((type) => {
        const slot = recommendations.find((item) => item.recommendation_type === type);
        const plan = slot?.status === "AVAILABLE" ? plans.find((item) => item.plan_id === slot.plan_id) ?? null : null;
        const selected = plan?.plan_id === selectedPlanId;
        const disabled = !slot || !plan;
        return (
          <Pressable
            accessibilityRole="tab"
            accessibilityLabel={disabled ? `${LABELS[type]}暂不可用，${slot?.reason || "没有可用方案"}` : `${LABELS[type]}，${formatMoney(plan.cost_breakdown.total_cost)}，${minutesToText(plan.total_duration_minutes)}`}
            accessibilityState={{ disabled, selected }}
            disabled={disabled}
            key={type}
            onPress={() => slot && plan && onSelect(plan, slot)}
            style={({ pressed }) => [styles.option, selected && styles.selected, disabled && styles.disabled, pressed && !disabled && styles.pressed]}
          >
            <Text numberOfLines={1} style={[styles.label, selected && styles.selectedText, disabled && styles.disabledText]}>{LABELS[type]}</Text>
            <Text adjustsFontSizeToFit minimumFontScale={0.82} numberOfLines={1} style={[styles.value, selected && styles.selectedText, disabled && styles.disabledText]}>{plan ? `${formatMoney(plan.cost_breakdown.total_cost)} · ${minutesToText(plan.total_duration_minutes)}` : "暂不可用"}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  selector: { backgroundColor: ui.colors.disabled, borderRadius: ui.radius.card, flexDirection: "row", gap: ui.spacing.xs, padding: ui.spacing.xxs },
  option: { alignItems: "center", borderRadius: ui.radius.small, flex: 1, justifyContent: "center", minHeight: ui.touchTarget, minWidth: 0, paddingHorizontal: ui.spacing.xxs, paddingVertical: ui.spacing.sm },
  selected: { backgroundColor: ui.colors.surface, shadowColor: ui.colors.primaryDeep, shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.1, shadowRadius: 4 },
  disabled: { backgroundColor: ui.colors.disabled },
  pressed: { transform: [{ scale: 0.98 }] },
  label: { color: ui.colors.textSecondary, fontSize: 12, fontWeight: "700" },
  value: { color: ui.colors.text, fontSize: 10, fontWeight: "700", marginTop: 2 },
  selectedText: { color: ui.colors.primaryDeep },
  disabledText: { color: ui.colors.disabledText }
});
