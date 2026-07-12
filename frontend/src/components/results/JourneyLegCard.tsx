import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { RecalculateChangeType, Segment } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";
import { formatClockTime, segmentTitle, selectedOptionLabel, selectedTransferOption } from "./presentation";

type Props = { segment: Segment; expanded: boolean; busy: boolean; onToggle: () => void; onApply: (segment: Segment, changeType: RecalculateChangeType, optionId: string, label: string) => void };

function OptionButton({ label, selected, disabled, onPress }: { label: string; selected: boolean; disabled: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ disabled, selected }} disabled={disabled} onPress={onPress} style={({ pressed }) => [styles.option, selected && styles.optionSelected, disabled && styles.optionDisabled, pressed && !disabled && styles.pressed]}>
      <Text style={[styles.optionText, selected && styles.optionTextSelected, disabled && styles.optionTextDisabled]}>{label}</Text>
    </Pressable>
  );
}

function modeLabel(segment: Segment): string {
  if (segment.segment_type === "RAIL") return segment.train_number ? `高铁 ${segment.train_number}` : "铁路";
  if (segment.segment_type === "FLIGHT") return segment.flight_number ? `航班 ${segment.flight_number}` : "航班";
  return segment.transfer_mode === "WALK" ? "步行接驳" : "市内接驳";
}

export function JourneyLegCard({ segment, expanded, busy, onToggle, onApply }: Props) {
  const departure = formatClockTime(segment.departure_time);
  const arrival = formatClockTime(segment.arrival_time);
  const selectedTransfer = selectedTransferOption(segment);
  const hasOptions = Boolean(segment.seat_options?.length || segment.cabin_options?.length || segment.transfer_options?.length);
  return (
    <View style={styles.leg}>
      <Pressable accessibilityRole="button" accessibilityLabel={`${expanded ? "收起" : "展开"}${segmentTitle(segment)}的调整选项`} accessibilityState={{ expanded, disabled: !hasOptions }} disabled={!hasOptions} onPress={onToggle} style={({ pressed }) => [styles.header, pressed && hasOptions && styles.pressed]}>
        <View style={styles.copy}>
          <Text style={styles.mode}>{modeLabel(segment)}</Text>
          <Text style={styles.title}>{segmentTitle(segment)}</Text>
          <Text style={styles.meta}>{departure && arrival ? `${departure} 发车 · ${arrival} 到达` : "时间待确认"}{selectedOptionLabel(segment) ? `\n${selectedOptionLabel(segment)}` : ""}</Text>
          {selectedTransfer?.walking_distance_meters ? <Text style={styles.meta}>步行约 {selectedTransfer.walking_distance_meters} 米</Text> : null}
        </View>
        <View style={styles.aside}>
          <Text style={styles.duration}>{minutesToText(segment.duration_minutes)}</Text>
          {hasOptions ? <Text style={styles.expand}>{expanded ? "收起" : "调整"}</Text> : null}
        </View>
      </Pressable>
      {expanded ? (
        <View style={styles.options}>
          {selectedTransfer ? <Text style={styles.instruction}>{selectedTransfer.access_instruction} {selectedTransfer.ride_instruction} {selectedTransfer.egress_instruction}</Text> : null}
          {segment.seat_options?.map((option) => <OptionButton key={option.option_id} selected={option.option_id === segment.selected_seat_option_id} disabled={busy || option.option_id === segment.selected_seat_option_id} label={`${option.seat_type} · ${formatMoney(option.price)}`} onPress={() => onApply(segment, "SEAT_TYPE", option.option_id, option.seat_type)} />)}
          {segment.cabin_options?.map((option) => <OptionButton key={option.option_id} selected={option.option_id === segment.selected_cabin_option_id} disabled={busy || option.option_id === segment.selected_cabin_option_id} label={`${option.cabin_type} · ${formatMoney(option.price)}`} onPress={() => onApply(segment, "CABIN_TYPE", option.option_id, option.cabin_type)} />)}
          {segment.transfer_options?.map((option) => <OptionButton key={option.option_id} selected={option.option_id === segment.option_id} disabled={busy || option.option_id === segment.option_id} label={`${option.label} · ${formatMoney(option.estimated_cost)} · ${minutesToText(option.duration_minutes)}`} onPress={() => onApply(segment, "LOCAL_TRANSFER_MODE", option.option_id, option.label)} />)}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  leg: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, marginBottom: ui.spacing.sm, padding: ui.spacing.md },
  header: { alignItems: "flex-start", flexDirection: "row", minHeight: ui.touchTarget },
  copy: { flex: 1, paddingRight: ui.spacing.md },
  mode: { alignSelf: "flex-start", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.pill, color: ui.colors.primaryDeep, fontSize: 10, fontWeight: "800", lineHeight: 16, overflow: "hidden", paddingHorizontal: ui.spacing.sm, paddingVertical: ui.spacing.xxs },
  title: { color: ui.colors.text, fontSize: 14, fontWeight: "800", lineHeight: 20, marginTop: ui.spacing.xs },
  meta: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 17, marginTop: ui.spacing.xs },
  aside: { alignItems: "flex-end", gap: ui.spacing.sm },
  duration: { color: ui.colors.primaryDeep, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  expand: { color: ui.colors.primary, fontSize: 12, fontWeight: "800" },
  options: { backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, gap: ui.spacing.sm, marginTop: ui.spacing.sm, padding: ui.spacing.sm },
  instruction: { color: ui.colors.text, fontSize: 12, lineHeight: 18 },
  option: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.small, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md, paddingVertical: ui.spacing.sm },
  optionSelected: { backgroundColor: ui.colors.connection },
  optionDisabled: { backgroundColor: ui.colors.disabled },
  optionText: { color: ui.colors.text, fontSize: 13, fontWeight: "700" },
  optionTextSelected: { color: ui.colors.primaryDeep },
  optionTextDisabled: { color: ui.colors.disabledText },
  pressed: { opacity: 0.75, transform: [{ scale: 0.98 }] }
});
