import type { LocalTransferOption, Segment, TimePoint } from "../../types";

export function formatClockTime(time?: TimePoint | null) {
  if (!time?.datetime) return null;
  const parsed = new Date(time.datetime);
  if (Number.isNaN(parsed.getTime())) return time.datetime;
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(parsed).replace(/^24:/, "00:");
}

export function segmentTitle(segment: Segment) {
  if (segment.segment_type === "RAIL") return `${segment.train_number ?? "铁路"} ${segment.origin_station ?? "起点站"} → ${segment.destination_station ?? "终点站"}`;
  if (segment.segment_type === "FLIGHT") return `${segment.flight_number ?? "航班"} ${segment.origin_airport ?? "出发机场"} → ${segment.destination_airport ?? "到达机场"}`;
  return `${transferModeLabel(segment.transfer_mode)} ${segment.origin ?? "起点"} → ${segment.destination ?? "终点"}`;
}

export function segmentEndpoints(segment: Segment) {
  if (segment.segment_type === "RAIL") return { origin: segment.origin_station ?? "起点站", destination: segment.destination_station ?? "终点站" };
  if (segment.segment_type === "FLIGHT") return { origin: segment.origin_airport ?? "出发机场", destination: segment.destination_airport ?? "到达机场" };
  return { origin: segment.origin ?? "起点", destination: segment.destination ?? "终点" };
}

export function transferModeLabel(mode?: string) {
  const value = (mode ?? "").replace("transfer_", "").toUpperCase();
  if (value === "TAXI") return "打车";
  if (value === "SUBWAY") return "地铁";
  if (value === "BUS") return "公交";
  if (value === "WALK") return "步行";
  return "市内接驳";
}

export function selectedTransferOption(segment: Segment): LocalTransferOption | null {
  return segment.transfer_options?.find((option) => option.option_id === segment.option_id) ?? segment.transfer_options?.[0] ?? null;
}

export function selectedOptionLabel(segment: Segment) {
  if (segment.segment_type === "RAIL") return segment.seat_options?.find((option) => option.option_id === segment.selected_seat_option_id)?.seat_type ?? null;
  if (segment.segment_type === "FLIGHT") return segment.cabin_options?.find((option) => option.option_id === segment.selected_cabin_option_id)?.cabin_type ?? null;
  return selectedTransferOption(segment)?.label ?? transferModeLabel(segment.transfer_mode);
}
