import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { RecalculateChangeType, Segment } from "../../types";
import { formatMoney, minutesToText } from "../../utils/format";
import type { SegmentPricePresentation } from "../../utils/routePlanning";
import {
  formatClockTime,
  segmentEndpoints,
  selectedOptionLabel,
  selectedTransferOption,
  transferModeLabel
} from "./presentation";

type Props = {
  segment: Segment;
  price: SegmentPricePresentation;
  expanded: boolean;
  busy: boolean;
  last: boolean;
  onToggle: () => void;
  onApply: (
    segment: Segment,
    changeType: RecalculateChangeType,
    optionId: string,
    label: string
  ) => void;
};

function OptionButton({
  label,
  selected,
  disabled,
  onPress
}: {
  label: string;
  selected: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{ disabled, selected }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        selected && styles.optionSelected,
        disabled && !selected && styles.optionDisabled,
        pressed && !disabled && styles.pressed
      ]}
    >
      <Text style={[styles.optionText, selected && styles.optionTextSelected, disabled && !selected && styles.optionTextDisabled]}>{label}</Text>
    </Pressable>
  );
}

function modeLabel(segment: Segment): string {
  if (segment.segment_type === "RAIL") return segment.train_number ? `高铁 ${segment.train_number}` : "铁路";
  if (segment.segment_type === "FLIGHT") return segment.flight_number ? `航班 ${segment.flight_number}` : "航班";
  return transferModeLabel(segment.transfer_mode);
}

export function JourneyLegCard({
  segment,
  price,
  expanded,
  busy,
  last,
  onToggle,
  onApply
}: Props) {
  const departure = formatClockTime(segment.departure_time);
  const arrival = formatClockTime(segment.arrival_time);
  const endpoints = segmentEndpoints(segment);
  const selectedLabel = selectedOptionLabel(segment);
  const selectedTransfer = selectedTransferOption(segment);
  const verifiedTransferOptions = segment.transfer_options?.filter((option) => option.route_status !== "UNAVAILABLE") ?? [];
  const hasSeatOptions = Boolean(segment.seat_options?.length);
  const hasCabinOptions = Boolean(segment.cabin_options?.length);
  const hasTransferOptions = verifiedTransferOptions.length > 1;
  const hasOptions = hasSeatOptions || hasCabinOptions || hasTransferOptions;
  const adjustmentLabel = hasSeatOptions ? "更换席别" : hasCabinOptions ? "更换舱位" : "调整接驳";
  const selectedPriceText = price ? formatMoney(price.money) : null;
  const accessibilityLabel = `${adjustmentLabel}，当前${selectedLabel ?? "待确认"}${selectedPriceText ? `，票价${selectedPriceText}` : ""}`;

  return (
    <View style={styles.leg}>
      <View style={styles.rail}>
        <View style={styles.node} />
        {!last ? <View style={styles.line} /> : null}
      </View>
      <View style={styles.copy}>
        <View style={styles.topline}>
          <Text style={styles.time}>{departure && arrival ? `${departure} - ${arrival}` : "时间待确认"}</Text>
          <Text style={styles.mode}>{modeLabel(segment)}</Text>
        </View>
        <Text style={styles.title}>{endpoints.origin} → {endpoints.destination}</Text>
        <Text style={styles.meta}>
          {minutesToText(segment.duration_minutes)}
          {selectedTransfer?.walking_distance_meters ? ` · 步行约 ${selectedTransfer.walking_distance_meters} 米` : ""}
          {segment.route_status === "UNAVAILABLE" ? " · 当前接驳不可用" : ""}
        </Text>

        {price && !hasSeatOptions && !hasCabinOptions ? (
          <View style={styles.costRow}>
            <Text style={styles.costLabel}>{price.label}</Text>
            <Text style={styles.costValue}>{formatMoney(price.money)}{price.estimated ? "  估算" : ""}</Text>
          </View>
        ) : null}

        {hasOptions ? (
          <Pressable
            accessibilityLabel={accessibilityLabel}
            accessibilityRole="button"
            accessibilityState={{ disabled: busy, expanded }}
            disabled={busy}
            onPress={onToggle}
            style={({ pressed }) => [styles.adjustment, pressed && !busy && styles.pressed]}
          >
            <View style={styles.adjustmentCopy}>
              <Text style={styles.adjustmentLabel}>{hasSeatOptions ? "已选席别" : hasCabinOptions ? "已选舱位" : "当前接驳"}</Text>
              <Text numberOfLines={1} style={styles.adjustmentValue}>
                {selectedLabel ?? "待确认"}{selectedPriceText ? ` · ${selectedPriceText}` : ""}
              </Text>
            </View>
            <Text style={styles.adjustmentAction}>{expanded ? "收起" : `${adjustmentLabel} ›`}</Text>
          </Pressable>
        ) : null}

        {expanded ? (
          <View style={styles.options}>
            {selectedTransfer ? <Text style={styles.instruction}>{selectedTransfer.access_instruction} {selectedTransfer.ride_instruction} {selectedTransfer.egress_instruction}</Text> : null}
            {segment.seat_options?.map((option) => (
              <OptionButton
                disabled={busy || option.option_id === segment.selected_seat_option_id}
                key={option.option_id}
                label={`${option.seat_type} · ${formatMoney(option.price)}`}
                onPress={() => onApply(segment, "SEAT_TYPE", option.option_id, option.seat_type)}
                selected={option.option_id === segment.selected_seat_option_id}
              />
            ))}
            {segment.cabin_options?.map((option) => (
              <OptionButton
                disabled={busy || option.option_id === segment.selected_cabin_option_id}
                key={option.option_id}
                label={`${option.cabin_type} · ${formatMoney(option.price)}`}
                onPress={() => onApply(segment, "CABIN_TYPE", option.option_id, option.cabin_type)}
                selected={option.option_id === segment.selected_cabin_option_id}
              />
            ))}
            {verifiedTransferOptions.map((option) => (
              <OptionButton
                disabled={busy || option.option_id === segment.option_id}
                key={option.option_id}
                label={`${option.label} · ${formatMoney(option.estimated_cost)} · ${minutesToText(option.duration_minutes)}`}
                onPress={() => onApply(segment, "LOCAL_TRANSFER_MODE", option.option_id, option.label)}
                selected={option.option_id === segment.option_id}
              />
            ))}
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  leg: { flexDirection: "row", paddingHorizontal: 14, paddingTop: 13 },
  rail: { alignItems: "center", width: 28 },
  node: { backgroundColor: ui.colors.surface, borderColor: ui.colors.primary, borderRadius: ui.radius.pill, borderWidth: 3, height: 13, marginTop: 2, width: 13, zIndex: 1 },
  line: { backgroundColor: ui.colors.connection, bottom: -13, position: "absolute", top: 15, width: 2 },
  copy: { flex: 1, minWidth: 0, paddingBottom: ui.spacing.md, paddingLeft: ui.spacing.sm },
  topline: { alignItems: "center", flexDirection: "row", gap: ui.spacing.sm, justifyContent: "space-between" },
  time: { color: ui.colors.primaryDeep, flex: 1, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  mode: { backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.pill, color: ui.colors.primaryDeep, flexShrink: 0, fontSize: 10, fontWeight: "800", lineHeight: 16, overflow: "hidden", paddingHorizontal: ui.spacing.sm, paddingVertical: 2 },
  title: { color: ui.colors.text, fontSize: 13, fontWeight: "800", lineHeight: 18, marginTop: ui.spacing.xs },
  meta: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 16, marginTop: 3 },
  costRow: { alignItems: "center", borderTopColor: ui.colors.line, borderTopWidth: StyleSheet.hairlineWidth, flexDirection: "row", gap: ui.spacing.md, justifyContent: "space-between", marginTop: ui.spacing.sm, minHeight: 34 },
  costLabel: { color: ui.colors.textSecondary, flex: 1, fontSize: 11, lineHeight: 16 },
  costValue: { color: ui.colors.text, flexShrink: 0, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  adjustment: { alignItems: "center", borderTopColor: ui.colors.line, borderTopWidth: StyleSheet.hairlineWidth, flexDirection: "row", gap: ui.spacing.md, justifyContent: "space-between", marginTop: ui.spacing.sm, minHeight: ui.touchTarget },
  adjustmentCopy: { alignItems: "baseline", flex: 1, flexDirection: "row", gap: ui.spacing.xs, minWidth: 0 },
  adjustmentLabel: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15 },
  adjustmentValue: { color: ui.colors.text, flex: 1, fontSize: 13, fontWeight: "800", lineHeight: 18, minWidth: 0 },
  adjustmentAction: { color: ui.colors.primary, flexShrink: 0, fontSize: 12, fontWeight: "800", lineHeight: 18 },
  options: { gap: ui.spacing.sm, paddingBottom: ui.spacing.sm },
  instruction: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 17 },
  option: { backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.small, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md, paddingVertical: ui.spacing.sm },
  optionSelected: { backgroundColor: ui.colors.connection },
  optionDisabled: { backgroundColor: ui.colors.disabled },
  optionText: { color: ui.colors.text, fontSize: 13, fontWeight: "700" },
  optionTextSelected: { color: ui.colors.primaryDeep },
  optionTextDisabled: { color: ui.colors.disabledText },
  pressed: { opacity: 0.78, transform: [{ scale: 0.98 }] }
});
