import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  ImageBackground,
  type ImageSourcePropType,
  Linking,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View
} from "react-native";
import qingdaoHero from "../assets/destination-scenes/qingdao-pier.jpg";
import { bookingRedirect, planTrip, recalculate } from "./api/client";
import type { DestinationPresentation, LocalTransferOption, RecommendationSlot, Segment, TravelPlan, TravelPlanResponse } from "./types";
import { formatMoney, minutesToText, riskLabel, slotLabel } from "./utils/format";

const SAMPLE_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。";

const HERO_IMAGES: Record<string, ImageSourcePropType> = {
  qingdao: qingdaoHero
};

function findPlan(response: TravelPlanResponse | null, planId: string | null) {
  if (!response || !planId) return null;
  return response.plans.find((plan) => plan.plan_id === planId) ?? null;
}

function preferredRecommendationPlanId(response: TravelPlanResponse | null) {
  if (!response) return null;
  const recommendations = response.recommendation_result?.recommendations ?? [];
  const availableRecommendations = recommendations.filter((slot) => slot.status === "AVAILABLE" && slot.plan_id);
  const preferredType = response.travel_request.preferences.find((preference) => availableRecommendations.some((slot) => slot.recommendation_type === preference));
  return availableRecommendations.find((slot) => slot.recommendation_type === preferredType)?.plan_id ?? availableRecommendations[0]?.plan_id ?? null;
}

function planTypeLabel(type: string) {
  const labels: Record<string, string> = {
    DIRECT_RAIL: "高铁直达",
    TRANSFER_RAIL: "高铁中转",
    MULTI_TRANSFER_RAIL: "多段高铁",
    RAIL_TICKET_ENHANCEMENT: "票源增强",
    DIRECT_FLIGHT: "航班直飞",
    TRANSFER_FLIGHT: "航班中转",
    MULTI_AIRPORT_FLIGHT: "多机场组合",
    FLIGHT_RAIL_MIXED: "空铁混合",
    GROUND_ONLY: "地面交通",
    MIXED: "混合方案"
  };
  return labels[type] ?? type;
}

function transferModeLabel(mode: string) {
  const normalized = mode.replace("transfer_", "").toUpperCase();
  if (normalized === "TAXI") return "打车";
  if (normalized === "SUBWAY") return "地铁";
  if (normalized === "BUS") return "公交";
  if (normalized === "WALK") return "步行";
  return mode.replace("transfer_", "");
}

function segmentTitle(segment: Segment) {
  if (segment.segment_type === "RAIL") return `${segment.train_number} ${segment.origin_station} 到 ${segment.destination_station}`;
  if (segment.segment_type === "FLIGHT") return `${segment.flight_number} ${segment.origin_airport} 到 ${segment.destination_airport}`;
  return `${transferModeLabel(segment.transfer_mode ?? "")} ${segment.origin} 到 ${segment.destination}`;
}

function segmentModeLabel(segment: Segment) {
  if (segment.segment_type === "LOCAL_TRANSFER") return transferModeLabel(segment.transfer_mode ?? "");
  if (segment.segment_type === "RAIL") return "高铁";
  if (segment.segment_type === "FLIGHT") return "航班";
  return segment.segment_type;
}

function planDisplayName(plan: TravelPlan) {
  const originalParts = plan.plan_name.split("+").map((part) => part.trim());
  if (originalParts.length === plan.segments.length) {
    return plan.segments.map((segment, index) => (segment.segment_type === "LOCAL_TRANSFER" ? segmentModeLabel(segment) : originalParts[index])).join(" + ");
  }
  return plan.segments.map(segmentModeLabel).join(" + ");
}

function fallbackTransferOption(segment: Segment, optionId: string): LocalTransferOption {
  const mode = optionId.replace("transfer_", "").toUpperCase();
  const label = transferModeLabel(optionId);
  return {
    option_id: optionId,
    transfer_mode: mode,
    label,
    estimated_cost: segment.estimated_cost ?? { amount_minor: 0, currency: "CNY", scale: 2, is_estimated: true, display_text: "待估算" },
    duration_minutes: segment.duration_minutes,
    access_station: mode === "TAXI" ? null : `${segment.origin ?? "出发地"}附近${mode === "SUBWAY" ? "地铁站" : "公交站"}`,
    egress_station: mode === "TAXI" ? null : `${segment.destination ?? "目的地"}附近${mode === "SUBWAY" ? "地铁站" : "公交站"}`,
    access_instruction: mode === "TAXI" ? `从 ${segment.origin} 上车。` : `从 ${segment.origin} 前往上车站点。`,
    ride_instruction: mode === "TAXI" ? `直达 ${segment.destination}。` : `乘坐${label}到下车站点。`,
    egress_instruction: mode === "TAXI" ? `在 ${segment.destination} 下车。` : `从下车站点前往 ${segment.destination}。`,
    walking_distance_meters: 0,
    data_source: segment.data_source
  };
}

function transferOptionsFor(segment: Segment) {
  return segment.transfer_options?.length ? segment.transfer_options : segment.available_options?.map((option) => fallbackTransferOption(segment, option)) ?? [];
}

function selectedTransferOption(segment: Segment) {
  return transferOptionsFor(segment).find((option) => option.option_id === segment.option_id) ?? transferOptionsFor(segment)[0] ?? null;
}

function selectedRailSeat(segment: Segment) {
  return segment.seat_options?.find((option) => option.option_id === segment.selected_seat_option_id) ?? segment.seat_options?.[0] ?? null;
}

function selectedFlightCabin(segment: Segment) {
  return segment.cabin_options?.find((option) => option.option_id === segment.selected_cabin_option_id) ?? segment.cabin_options?.[0] ?? null;
}

function Hero({ presentation, plan }: { presentation: DestinationPresentation | null; plan: TravelPlan | null }) {
  const destinationKey = presentation?.destination_key ?? "generic";
  const imageSource = HERO_IMAGES[destinationKey];
  const content = (
    <View style={styles.heroShade}>
      <Text style={styles.heroKicker}>目的地</Text>
      <Text style={styles.heroTitle}>{presentation?.display_name ?? "出行搭子"}</Text>
      {plan && (
        <Text style={styles.heroMeta}>
          {planDisplayName(plan)} · {minutesToText(plan.total_duration_minutes)} · {formatMoney(plan.cost_breakdown.total_cost)}
        </Text>
      )}
    </View>
  );

  if (!imageSource) {
    return <View style={[styles.hero, styles.heroFallback]}>{content}</View>;
  }
  return (
    <ImageBackground source={imageSource} style={styles.hero} imageStyle={styles.heroImage}>
      {content}
    </ImageBackground>
  );
}

function RecommendationCard({ slot, plan, selected, onSelect }: { slot: RecommendationSlot; plan: TravelPlan | null; selected: boolean; onSelect: (plan: TravelPlan) => void }) {
  return (
    <Pressable style={[styles.card, styles.recommendationCard, selected && styles.cardSelected]} disabled={!plan} onPress={() => plan && onSelect(plan)}>
      <View style={styles.rowBetween}>
        <Text style={styles.kicker}>{slotLabel(slot.recommendation_type)}</Text>
        <Text style={[styles.riskPill, riskStyle(plan?.risk_assessment.overall_risk_level ?? slot.status)]}>{plan ? riskLabel(plan.risk_assessment.overall_risk_level) : slot.status}</Text>
      </View>
      {plan ? (
        <>
          <Text style={styles.cardTitle}>{planDisplayName(plan)}</Text>
          <Text style={styles.secondaryText}>{planTypeLabel(plan.plan_type)}</Text>
          <View style={styles.metricRow}>
            <Text style={styles.metricText}>{formatMoney(plan.cost_breakdown.total_cost)}</Text>
            <Text style={styles.metricText}>{minutesToText(plan.total_duration_minutes)}</Text>
          </View>
        </>
      ) : (
        <Text style={styles.cardTitle}>{slot.reason || "当前不可推荐"}</Text>
      )}
    </Pressable>
  );
}

function SegmentTimeline({ segments }: { segments: Segment[] }) {
  return (
    <View style={styles.timeline}>
      {segments.map((segment, index) => (
        <View style={styles.timelineRow} key={segment.segment_id}>
          <View style={styles.timelineIndex}>
            <Text style={styles.timelineIndexText}>{index + 1}</Text>
          </View>
          <View style={styles.timelineCopy}>
            <Text style={styles.timelineTitle}>{segmentTitle(segment)}</Text>
            <Text style={styles.secondaryText}>
              {segmentModeLabel(segment)} · {minutesToText(segment.duration_minutes)}
            </Text>
          </View>
        </View>
      ))}
    </View>
  );
}

function TransferRouteSummary({ option }: { option: LocalTransferOption }) {
  return (
    <View style={styles.transferSummary}>
      {(option.access_station || option.egress_station) && (
        <Text style={styles.secondaryText}>
          {option.access_station ?? "上车点"} 到 {option.egress_station ?? "下车点"}
        </Text>
      )}
      <Text style={styles.bodyText}>
        {option.access_instruction} {option.ride_instruction} {option.egress_instruction}
      </Text>
    </View>
  );
}

function DetailPanel({ plan, onRecalculated }: { plan: TravelPlan; onRecalculated: (plan: TravelPlan) => void }) {
  const [busy, setBusy] = useState(false);
  const [expandedSegmentId, setExpandedSegmentId] = useState<string | null>(null);

  async function applyOption(segment: Segment, changeType: "RAIL_SEAT" | "FLIGHT_CABIN" | "LOCAL_TRANSFER", optionId: string, label: string) {
    setBusy(true);
    try {
      const response = await recalculate(plan.plan_id, segment.segment_id, changeType, optionId, label);
      onRecalculated(response.plan);
      Alert.alert("已重算", `${response.change_summary.message} ${response.change_summary.cost_delta.display_text}`);
    } catch (error) {
      Alert.alert("重算失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function openRedirect() {
    const first = plan.segments.find((segment) => segment.segment_type === "RAIL" || segment.segment_type === "FLIGHT");
    const redirectType = first?.segment_type === "FLIGHT" ? "AIRLINE" : "RAIL_12306";
    setBusy(true);
    try {
      const response = await bookingRedirect(plan.plan_id, first?.segment_id ?? null, redirectType);
      if (response.redirect.url_available && response.redirect.url) {
        await Linking.openURL(response.redirect.url);
      } else {
        Alert.alert("请手动确认", response.redirect.fallback_instruction ?? "请打开对应平台确认。");
      }
    } catch (error) {
      Alert.alert("跳转失败", error instanceof Error ? error.message : "请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.detail}>
      <View style={styles.rowBetween}>
        <View style={styles.flex}>
          <Text style={styles.kicker}>{planTypeLabel(plan.plan_type)}</Text>
          <Text style={styles.sectionTitle}>{planDisplayName(plan)}</Text>
        </View>
        <Pressable style={styles.iconButton} onPress={openRedirect} disabled={busy}>
          <Text style={styles.iconButtonText}>跳转</Text>
        </Pressable>
      </View>

      <View style={styles.metricBand}>
        <Text style={styles.metricText}>{formatMoney(plan.cost_breakdown.total_cost)}</Text>
        <Text style={styles.metricText}>{minutesToText(plan.total_duration_minutes)}</Text>
        <Text style={styles.metricText}>{riskLabel(plan.risk_assessment.overall_risk_level)}</Text>
      </View>

      <SegmentTimeline segments={plan.segments} />

      <Text style={styles.subheading}>费用明细</Text>
      {plan.cost_breakdown.items.map((item) => (
        <View style={styles.costRow} key={`${item.label}-${item.amount.amount_minor}`}>
          <Text style={styles.bodyText}>{item.label}</Text>
          <Text style={styles.costText}>{formatMoney(item.amount)}</Text>
        </View>
      ))}

      <Text style={styles.subheading}>风险提示</Text>
      {plan.risk_assessment.risk_items.map((risk) => (
        <View style={styles.notice} key={risk.risk_id}>
          <Text style={styles.noticeTitle}>{risk.title}</Text>
          <Text style={styles.secondaryText}>{risk.message}</Text>
        </View>
      ))}

      <Text style={styles.subheading}>可调整选项</Text>
      {plan.segments.map((segment) => {
        const expanded = expandedSegmentId === segment.segment_id;
        const transferOption = segment.segment_type === "LOCAL_TRANSFER" ? selectedTransferOption(segment) : null;
        const railSeat = segment.segment_type === "RAIL" ? selectedRailSeat(segment) : null;
        const flightCabin = segment.segment_type === "FLIGHT" ? selectedFlightCabin(segment) : null;
        return (
          <View style={styles.optionGroup} key={segment.segment_id}>
            <Pressable style={styles.rowBetween} onPress={() => setExpandedSegmentId(expanded ? null : segment.segment_id)}>
              <View style={styles.flex}>
                <Text style={styles.optionTitle}>{segmentTitle(segment)}</Text>
                {transferOption && <Text style={styles.secondaryText}>{transferOption.label} · {formatMoney(transferOption.estimated_cost)}</Text>}
                {railSeat && <Text style={styles.secondaryText}>{railSeat.seat_type} · {formatMoney(railSeat.price)}</Text>}
                {flightCabin && <Text style={styles.secondaryText}>{flightCabin.cabin_type} · {formatMoney(flightCabin.price)}</Text>}
              </View>
              <Text style={styles.expandText}>{expanded ? "收起" : "展开"}</Text>
            </Pressable>

            {expanded && (
              <View style={styles.optionPanel}>
                {transferOption && <TransferRouteSummary option={transferOption} />}
                {segment.seat_options?.map((option) => (
                  <OptionButton
                    key={option.option_id}
                    disabled={busy || option.option_id === segment.selected_seat_option_id}
                    label={`${option.seat_type} ${formatMoney(option.price)}`}
                    onPress={() => applyOption(segment, "RAIL_SEAT", option.option_id, option.seat_type)}
                  />
                ))}
                {segment.cabin_options?.map((option) => (
                  <OptionButton
                    key={option.option_id}
                    disabled={busy || option.option_id === segment.selected_cabin_option_id}
                    label={`${option.cabin_type} ${formatMoney(option.price)}`}
                    onPress={() => applyOption(segment, "FLIGHT_CABIN", option.option_id, option.cabin_type)}
                  />
                ))}
                {segment.segment_type === "LOCAL_TRANSFER" && transferOptionsFor(segment).map((option) => (
                  <OptionButton
                    key={option.option_id}
                    disabled={busy || option.option_id === segment.option_id}
                    label={`${option.label} ${formatMoney(option.estimated_cost)} · ${minutesToText(option.duration_minutes)}`}
                    onPress={() => applyOption(segment, "LOCAL_TRANSFER", option.option_id, option.label)}
                  />
                ))}
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

function OptionButton({ label, disabled, onPress }: { label: string; disabled?: boolean; onPress: () => void }) {
  return (
    <Pressable style={[styles.optionButton, disabled && styles.optionButtonDisabled]} disabled={disabled} onPress={onPress}>
      <Text style={[styles.optionButtonText, disabled && styles.optionButtonTextDisabled]}>{label}</Text>
    </Pressable>
  );
}

function riskStyle(level: string) {
  if (level === "LOW") return styles.riskLow;
  if (level === "MEDIUM") return styles.riskMedium;
  if (level === "HIGH") return styles.riskHigh;
  return styles.riskBlocked;
}

export default function App() {
  const [rawInput, setRawInput] = useState(SAMPLE_INPUT);
  const [response, setResponse] = useState<TravelPlanResponse | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const recommendations = response?.recommendation_result?.recommendations ?? [];
  const selectedPlan = useMemo(() => {
    const explicit = findPlan(response, selectedPlanId);
    if (explicit) return explicit;
    return findPlan(response, preferredRecommendationPlanId(response)) ?? response?.plans[0] ?? null;
  }, [response, selectedPlanId]);
  const recommendedPlanIds = useMemo(() => new Set(recommendations.map((slot) => slot.plan_id).filter(Boolean)), [recommendations]);
  const candidatePlans = useMemo(() => response?.plans.filter((plan) => !recommendedPlanIds.has(plan.plan_id)) ?? [], [response, recommendedPlanIds]);

  async function submit() {
    setLoading(true);
    setError("");
    try {
      const result = await planTrip(rawInput);
      setResponse(result);
      setSelectedPlanId(preferredRecommendationPlanId(result) ?? result.plans[0]?.plan_id ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }

  function replacePlan(updated: TravelPlan) {
    setResponse((current) => {
      if (!current) return current;
      return { ...current, plans: current.plans.map((plan) => (plan.plan_id === updated.plan_id ? updated : plan)) };
    });
    setSelectedPlanId(updated.plan_id);
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <View style={styles.topbar}>
          <Text style={styles.appTitle}>出行搭子</Text>
          <Text style={styles.appSubtitle}>Schema 1.15 · Redirect only</Text>
        </View>

        <Hero presentation={response?.destination_presentation ?? null} plan={selectedPlan} />

        <View style={styles.queryPanel}>
          <TextInput
            style={styles.input}
            value={rawInput}
            onChangeText={setRawInput}
            multiline
            placeholder="说说你从哪里出发、到哪里、什么时候走。"
            textAlignVertical="top"
          />
          <Pressable style={[styles.submitButton, loading && styles.submitButtonDisabled]} onPress={submit} disabled={loading}>
            {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.submitButtonText}>开始规划</Text>}
          </Pressable>
        </View>

        {error ? <Text style={styles.errorPanel}>{error}</Text> : null}

        {response && (
          <>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>推荐方案</Text>
              <Text style={styles.secondaryText}>{response.planning_status}</Text>
            </View>
            {recommendations.length === 0 && (
              <View style={[styles.card, styles.mutedCard]}>
                <Text style={styles.cardTitle}>推荐暂不可用</Text>
                <Text style={styles.secondaryText}>系统未使用代码生成三张推荐卡，你仍可以查看候选方案。</Text>
              </View>
            )}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
              {recommendations.map((slot) => (
                <RecommendationCard key={slot.recommendation_type} slot={slot} plan={findPlan(response, slot.plan_id)} selected={slot.plan_id === selectedPlan?.plan_id} onSelect={(plan) => setSelectedPlanId(plan.plan_id)} />
              ))}
            </ScrollView>

            {selectedPlan && <DetailPanel plan={selectedPlan} onRecalculated={replacePlan} />}

            <Text style={styles.sectionTitle}>候选方案</Text>
            {candidatePlans.map((plan) => (
              <Pressable style={[styles.candidate, plan.plan_id === selectedPlan?.plan_id && styles.candidateActive]} key={plan.plan_id} onPress={() => setSelectedPlanId(plan.plan_id)}>
                <View style={styles.flex}>
                  <Text style={styles.optionTitle}>{planDisplayName(plan)}</Text>
                  <Text style={styles.secondaryText}>
                    {planTypeLabel(plan.plan_type)} · {riskLabel(plan.risk_assessment.overall_risk_level)}
                  </Text>
                  {!plan.can_be_selected_by_llm && <Text style={styles.warningText}>{plan.block_reason_message ?? "不进入主推荐"}</Text>}
                </View>
                <Text style={styles.costText}>{formatMoney(plan.cost_breakdown.total_cost)}</Text>
              </Pressable>
            ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#f5f7f8"
  },
  screen: {
    flex: 1
  },
  content: {
    padding: 16,
    paddingBottom: 40
  },
  topbar: {
    marginBottom: 12
  },
  appTitle: {
    color: "#172126",
    fontSize: 28,
    fontWeight: "800"
  },
  appSubtitle: {
    color: "#66747c",
    fontSize: 13,
    marginTop: 2
  },
  hero: {
    minHeight: 164,
    borderRadius: 8,
    overflow: "hidden",
    marginBottom: 14
  },
  heroImage: {
    borderRadius: 8
  },
  heroFallback: {
    backgroundColor: "#234f5f"
  },
  heroShade: {
    flex: 1,
    justifyContent: "flex-end",
    padding: 18,
    backgroundColor: "rgba(10, 25, 31, 0.42)"
  },
  heroKicker: {
    color: "#d7f0ef",
    fontSize: 12,
    fontWeight: "700"
  },
  heroTitle: {
    color: "#ffffff",
    fontSize: 28,
    fontWeight: "800",
    marginTop: 4
  },
  heroMeta: {
    color: "#f1f6f7",
    fontSize: 13,
    marginTop: 8
  },
  queryPanel: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    padding: 12,
    gap: 10,
    marginBottom: 16
  },
  input: {
    minHeight: 112,
    color: "#172126",
    fontSize: 16,
    lineHeight: 23
  },
  submitButton: {
    alignItems: "center",
    backgroundColor: "#126b75",
    borderRadius: 8,
    minHeight: 48,
    justifyContent: "center"
  },
  submitButtonDisabled: {
    opacity: 0.72
  },
  submitButtonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "800"
  },
  errorPanel: {
    backgroundColor: "#fff0ed",
    borderRadius: 8,
    color: "#9d2f21",
    marginBottom: 12,
    padding: 12
  },
  sectionHeader: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 2
  },
  sectionTitle: {
    color: "#172126",
    fontSize: 20,
    fontWeight: "800"
  },
  horizontalList: {
    gap: 10,
    paddingVertical: 10
  },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    padding: 14
  },
  recommendationCard: {
    minHeight: 154,
    width: 244
  },
  cardSelected: {
    borderColor: "#126b75",
    borderWidth: 2
  },
  mutedCard: {
    marginVertical: 10
  },
  rowBetween: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12
  },
  flex: {
    flex: 1
  },
  kicker: {
    color: "#126b75",
    fontSize: 12,
    fontWeight: "800"
  },
  riskPill: {
    borderRadius: 999,
    color: "#ffffff",
    fontSize: 12,
    fontWeight: "800",
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4
  },
  riskLow: {
    backgroundColor: "#24735a"
  },
  riskMedium: {
    backgroundColor: "#956a1d"
  },
  riskHigh: {
    backgroundColor: "#a34226"
  },
  riskBlocked: {
    backgroundColor: "#757575"
  },
  cardTitle: {
    color: "#172126",
    fontSize: 17,
    fontWeight: "800",
    marginTop: 12
  },
  secondaryText: {
    color: "#66747c",
    fontSize: 13,
    lineHeight: 19
  },
  bodyText: {
    color: "#314047",
    fontSize: 14,
    lineHeight: 20
  },
  metricRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 14
  },
  metricText: {
    color: "#172126",
    fontSize: 14,
    fontWeight: "800"
  },
  detail: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    marginBottom: 16,
    padding: 14
  },
  iconButton: {
    backgroundColor: "#e7f2f3",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 9
  },
  iconButtonText: {
    color: "#126b75",
    fontWeight: "800"
  },
  metricBand: {
    backgroundColor: "#f2f6f7",
    borderRadius: 8,
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 12,
    padding: 12
  },
  timeline: {
    marginTop: 14,
    gap: 10
  },
  timelineRow: {
    flexDirection: "row",
    gap: 10
  },
  timelineIndex: {
    alignItems: "center",
    backgroundColor: "#126b75",
    borderRadius: 16,
    height: 32,
    justifyContent: "center",
    width: 32
  },
  timelineIndexText: {
    color: "#ffffff",
    fontWeight: "800"
  },
  timelineCopy: {
    flex: 1,
    paddingBottom: 4
  },
  timelineTitle: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  subheading: {
    color: "#172126",
    fontSize: 16,
    fontWeight: "800",
    marginTop: 18,
    marginBottom: 8
  },
  costRow: {
    alignItems: "center",
    borderTopColor: "#edf0f1",
    borderTopWidth: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 10
  },
  costText: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  notice: {
    backgroundColor: "#fff8e8",
    borderRadius: 8,
    marginBottom: 8,
    padding: 10
  },
  noticeTitle: {
    color: "#6f4a06",
    fontWeight: "800",
    marginBottom: 3
  },
  optionGroup: {
    borderColor: "#edf0f1",
    borderRadius: 8,
    borderWidth: 1,
    marginBottom: 10,
    padding: 10
  },
  optionTitle: {
    color: "#172126",
    fontSize: 15,
    fontWeight: "800"
  },
  expandText: {
    color: "#126b75",
    fontWeight: "800"
  },
  optionPanel: {
    gap: 8,
    marginTop: 10
  },
  transferSummary: {
    backgroundColor: "#f2f6f7",
    borderRadius: 8,
    padding: 10
  },
  optionButton: {
    backgroundColor: "#126b75",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 11
  },
  optionButtonDisabled: {
    backgroundColor: "#e1e7e8"
  },
  optionButtonText: {
    color: "#ffffff",
    fontWeight: "800",
    textAlign: "center"
  },
  optionButtonTextDisabled: {
    color: "#6e7d84"
  },
  candidate: {
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderRadius: 8,
    flexDirection: "row",
    gap: 12,
    marginTop: 10,
    padding: 12
  },
  candidateActive: {
    borderColor: "#126b75",
    borderWidth: 2
  },
  warningText: {
    color: "#9d2f21",
    fontSize: 12,
    marginTop: 4
  }
});
