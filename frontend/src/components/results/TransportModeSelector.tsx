import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { IntercityTransportMode, TravelPlanResponse } from "../../types";
import { deriveTransportModeAvailability } from "../../utils/routePlanning";

const MODES: IntercityTransportMode[] = ["RAIL", "FLIGHT"];

type Props = {
  response: TravelPlanResponse;
  selectedMode: IntercityTransportMode | null;
  busy: boolean;
  onSelect: (mode: IntercityTransportMode) => void;
  onRetry: () => void;
};

export function TransportModeSelector({ response, selectedMode, busy, onSelect, onRetry }: Props) {
  const options = useMemo(
    () => MODES.map((mode) => deriveTransportModeAvailability(response, mode)),
    [response]
  );
  const [expandedMode, setExpandedMode] = useState<IntercityTransportMode | null>(null);
  const expandedOption = options.find((option) => option.mode === expandedMode && option.status !== "AVAILABLE") ?? null;

  return (
    <View style={styles.group}>
      <View accessibilityLabel="按交通方式查看方案" style={styles.selector}>
        {options.map((option) => {
          const selected = option.status === "AVAILABLE" && selectedMode === option.mode;
          const excluded = option.status === "EXCLUDED";
          return (
            <Pressable
              accessibilityLabel={`${option.label}，${option.statusLabel}${option.status !== "AVAILABLE" ? `，${option.reason}` : ""}`}
              accessibilityRole="button"
              accessibilityState={{ disabled: excluded, selected }}
              disabled={excluded}
              key={option.mode}
              onPress={() => {
                if (option.status === "AVAILABLE") {
                  setExpandedMode(null);
                  onSelect(option.mode);
                } else {
                  setExpandedMode((current) => (current === option.mode ? null : option.mode));
                }
              }}
              style={({ pressed }) => [
                styles.option,
                selected && styles.optionSelected,
                option.status === "UNAVAILABLE" && styles.optionUnavailable,
                excluded && styles.optionExcluded,
                pressed && !excluded && styles.pressed
              ]}
            >
              <View style={styles.optionHead}>
                <Text style={[styles.label, selected && styles.labelSelected]}>{option.label}</Text>
                <View style={[styles.dot, styles[`dot${option.status}`]]} />
              </View>
              <Text numberOfLines={1} style={[styles.status, selected && styles.statusSelected]}>{option.statusLabel}</Text>
            </Pressable>
          );
        })}
      </View>
      {expandedOption ? (
        <View accessibilityLiveRegion="polite" style={styles.explanation}>
          <View style={styles.explanationCopy}>
            <Text style={styles.explanationTitle}>{expandedOption.label}{expandedOption.statusLabel}</Text>
            <Text style={styles.explanationBody}>{expandedOption.reason}</Text>
            {expandedOption.mode === "FLIGHT" ? <Text style={styles.explanationMeta}>不会生成占位航班、价格或预订入口。</Text> : null}
          </View>
          {expandedOption.retryable && response.async_job ? (
            <Pressable
              accessibilityLabel={`重试${expandedOption.label}数据来源`}
              accessibilityRole="button"
              disabled={busy}
              onPress={onRetry}
              style={({ pressed }) => [styles.retry, pressed && !busy && styles.pressed, busy && styles.retryDisabled]}
            >
              <Text style={styles.retryText}>{busy ? "重试中" : "重试来源"}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { gap: ui.spacing.sm },
  selector: { backgroundColor: ui.colors.disabled, borderRadius: ui.radius.control, flexDirection: "row", gap: ui.spacing.xxs, padding: ui.spacing.xxs },
  option: { borderRadius: ui.radius.small, flex: 1, justifyContent: "center", minHeight: 58, minWidth: 0, paddingHorizontal: ui.spacing.md, paddingVertical: ui.spacing.sm },
  optionSelected: { backgroundColor: ui.colors.surface },
  optionUnavailable: { backgroundColor: ui.colors.warningSurface },
  optionExcluded: { backgroundColor: ui.colors.disabled },
  optionHead: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  label: { color: ui.colors.text, fontSize: 14, fontWeight: "800", lineHeight: 19 },
  labelSelected: { color: ui.colors.primaryDeep },
  status: { color: ui.colors.textSecondary, fontSize: 11, fontWeight: "600", lineHeight: 16, marginTop: 2 },
  statusSelected: { color: ui.colors.primary },
  dot: { borderRadius: ui.radius.pill, height: 8, width: 8 },
  dotAVAILABLE: { backgroundColor: ui.colors.success },
  dotEMPTY: { backgroundColor: ui.colors.textSecondary },
  dotUNAVAILABLE: { backgroundColor: ui.colors.warning },
  dotEXCLUDED: { backgroundColor: ui.colors.disabledText },
  explanation: { alignItems: "flex-start", backgroundColor: ui.colors.warningSurface, borderRadius: ui.radius.control, flexDirection: "row", gap: ui.spacing.sm, padding: ui.spacing.md },
  explanationCopy: { flex: 1, gap: ui.spacing.xxs },
  explanationTitle: { color: ui.colors.warning, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  explanationBody: { color: ui.colors.text, fontSize: 13, lineHeight: 19 },
  explanationMeta: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 16 },
  retry: { alignItems: "center", backgroundColor: ui.colors.surface, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  retryDisabled: { backgroundColor: ui.colors.disabled },
  retryText: { color: ui.colors.primaryDeep, fontSize: 12, fontWeight: "800" },
  pressed: { opacity: 0.82, transform: [{ scale: 0.98 }] }
});
