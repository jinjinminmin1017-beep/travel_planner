import { AlertTriangle, ChevronDown, ChevronUp, Clock, ExternalLink, Plane, RefreshCw, Search, Train, WalletCards } from "lucide-react";
import { useMemo, useState } from "react";
import { bookingRedirect, planTrip, recalculate } from "./api/client";
import type { LocalTransferOption, RecommendationSlot, Segment, TravelPlan, TravelPlanResponse } from "./types";
import { formatMoney, minutesToText, riskLabel, slotLabel } from "./utils/format";

const SAMPLE_INPUT = "我 2026 年 5 月 21 日上午 9 点后，从上海嘉定南翔格林公馆出发，到青岛金水假日酒店，帮我找最舒服和最便宜的方式。";

function SegmentIcon({ type }: { type: string }) {
  if (type === "RAIL") return <Train size={18} />;
  if (type === "FLIGHT") return <Plane size={18} />;
  return <Clock size={18} />;
}

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
    MULTI_AIRPORT_FLIGHT: "多机场",
    FLIGHT_RAIL_MIXED: "空铁混合"
  };
  return labels[type] ?? type;
}

function transferModeLabel(mode: string) {
  const normalized = mode.replace("transfer_", "").toUpperCase();
  if (normalized === "TAXI") return "打车";
  if (normalized === "SUBWAY") return "地铁";
  if (normalized === "BUS") return "公交";
  return mode.replace("transfer_", "");
}

function segmentTitle(segment: Segment) {
  if (segment.segment_type === "RAIL") return `${segment.train_number} ${segment.origin_station} → ${segment.destination_station}`;
  if (segment.segment_type === "FLIGHT") return `${segment.flight_number} ${segment.origin_airport} → ${segment.destination_airport}`;
  return `${transferModeLabel(segment.transfer_mode ?? "")} ${segment.origin} → ${segment.destination}`;
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

function destinationThemeClass(response: TravelPlanResponse | null) {
  if (!response) return "";
  const destinationSignal = (response.travel_request.destination_text || response.travel_request.raw_user_input).toLowerCase();
  if (destinationSignal.includes("北京") || destinationSignal.includes("beijing")) return "has-destination-theme destination-theme-beijing";
  if (destinationSignal.includes("上海") || destinationSignal.includes("shanghai")) return "has-destination-theme destination-theme-shanghai";
  if (destinationSignal.includes("青岛") || destinationSignal.includes("qingdao")) return "has-destination-theme destination-theme-qingdao";
  if (destinationSignal.includes("广州") || destinationSignal.includes("guangzhou")) return "has-destination-theme destination-theme-guangzhou";
  if (destinationSignal.includes("深圳") || destinationSignal.includes("shenzhen")) return "has-destination-theme destination-theme-shenzhen";
  if (destinationSignal.includes("成都") || destinationSignal.includes("chengdu")) return "has-destination-theme destination-theme-chengdu";
  if (destinationSignal.includes("杭州") || destinationSignal.includes("hangzhou")) return "has-destination-theme destination-theme-hangzhou";
  if (destinationSignal.includes("西安") || destinationSignal.includes("xian") || destinationSignal.includes("xi'an")) return "has-destination-theme destination-theme-xian";
  return "has-destination-theme destination-theme-generic";
}

function destinationDisplayName(response: TravelPlanResponse | null) {
  if (!response) return "";
  const destinationText = response.travel_request.destination_text?.trim() || "";
  const destinationSignal = (destinationText || response.travel_request.raw_user_input).toLowerCase();
  if (destinationSignal.includes("北京") || destinationSignal.includes("beijing")) return "北京";
  if (destinationSignal.includes("上海") || destinationSignal.includes("shanghai")) return "上海";
  if (destinationSignal.includes("青岛") || destinationSignal.includes("qingdao")) return "青岛";
  if (destinationSignal.includes("广州") || destinationSignal.includes("guangzhou")) return "广州";
  if (destinationSignal.includes("深圳") || destinationSignal.includes("shenzhen")) return "深圳";
  if (destinationSignal.includes("成都") || destinationSignal.includes("chengdu")) return "成都";
  if (destinationSignal.includes("杭州") || destinationSignal.includes("hangzhou")) return "杭州";
  if (destinationSignal.includes("西安") || destinationSignal.includes("xian") || destinationSignal.includes("xi'an")) return "西安";
  return destinationText || "目的地";
}

function TransferRouteSummary({ option, detailed = false }: { option: LocalTransferOption; detailed?: boolean }) {
  return (
    <div className={detailed ? "transfer-route" : "transfer-route compact"}>
      {(option.access_station || option.egress_station) && (
        <small>
          {option.access_station ?? "上车点"} → {option.egress_station ?? "下车点"}
        </small>
      )}
      {detailed ? (
        <>
          <p>{option.access_instruction}</p>
          <p>{option.ride_instruction}</p>
          <p>{option.egress_instruction}</p>
        </>
      ) : (
        <p>{option.access_instruction} {option.ride_instruction} {option.egress_instruction}</p>
      )}
    </div>
  );
}

function RecommendationCard({ slot, plan, selected, onSelect }: { slot: RecommendationSlot; plan: TravelPlan | null; selected: boolean; onSelect: (plan: TravelPlan) => void }) {
  return (
    <section className={selected ? "card recommendation-card selected" : "card recommendation-card"}>
      <div className="card-topline">
        <span className="eyebrow">{slotLabel(slot.recommendation_type)}</span>
        <span className={`risk ${plan?.risk_assessment.overall_risk_level ?? slot.status}`}>{plan ? riskLabel(plan.risk_assessment.overall_risk_level) : slot.status}</span>
      </div>
      {plan ? (
        <>
          <h2>{planDisplayName(plan)}</h2>
          <span className="plan-type">{planTypeLabel(plan.plan_type)}</span>
          <div className="metric-row">
            <span><WalletCards size={16} />{formatMoney(plan.cost_breakdown.total_cost)}</span>
            <span><Clock size={16} />{minutesToText(plan.total_duration_minutes)}</span>
          </div>
          <button className="primary-action" onClick={() => onSelect(plan)}>查看详情</button>
        </>
      ) : (
        <>
          <h2>{slot.status}</h2>
        </>
      )}
    </section>
  );
}

function SegmentTimeline({ segments }: { segments: Segment[] }) {
  return (
    <div className="timeline">
      {segments.map((segment, index) => (
        <div className="timeline-row" key={segment.segment_id}>
          <span className="timeline-icon">
            <SegmentIcon type={segment.segment_type} />
            <small>{index + 1}</small>
          </span>
          <div>
            <strong>{segmentTitle(segment)}</strong>
            <span>{minutesToText(segment.duration_minutes)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function DetailPanel({ plan, onRecalculated }: { plan: TravelPlan; onRecalculated: (plan: TravelPlan) => void }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [expandedSegments, setExpandedSegments] = useState<Record<string, boolean>>({});
  const displayName = planDisplayName(plan);

  function toggleSegment(segmentId: string) {
    setExpandedSegments((current) => ({ ...current, [segmentId]: !current[segmentId] }));
  }

  async function applyOption(segment: Segment, changeType: "RAIL_SEAT" | "FLIGHT_CABIN" | "LOCAL_TRANSFER", optionId: string, label: string) {
    setBusy(true);
    setMessage("");
    try {
      const response = await recalculate(plan.plan_id, segment.segment_id, changeType, optionId, label);
      onRecalculated(response.plan);
      setMessage(`${response.change_summary.message} ${response.change_summary.cost_delta.display_text}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重算失败");
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
        window.open(response.redirect.url, "_blank", "noopener,noreferrer");
      } else {
        setMessage(response.redirect.fallback_instruction ?? "请手动打开对应平台确认。");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "跳转失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="detail-grid">
      <div className="detail-main">
        <div className="section-heading">
          <div>
            <span className="eyebrow">{planTypeLabel(plan.plan_type)}</span>
            <h2>{displayName}</h2>
          </div>
          <button title="生成跳转" className="icon-button" onClick={openRedirect} disabled={busy}><ExternalLink size={18} /></button>
        </div>
        <div className="detail-metrics">
          <span><WalletCards size={16} />{formatMoney(plan.cost_breakdown.total_cost)}</span>
          <span><Clock size={16} />{minutesToText(plan.total_duration_minutes)}</span>
          <span><AlertTriangle size={16} />{riskLabel(plan.risk_assessment.overall_risk_level)}</span>
        </div>
        <SegmentTimeline segments={plan.segments} />
        <h3 className="subheading">费用明细</h3>
        <div className="cost-list">
          {plan.cost_breakdown.items.map((item) => (
            <div key={`${item.label}-${item.amount.amount_minor}`}>
              <span>{item.label}</span>
              <strong>{formatMoney(item.amount)}</strong>
            </div>
          ))}
        </div>
        <div className="total-line">
          <span>总费用</span>
          <strong>{formatMoney(plan.cost_breakdown.total_cost)}</strong>
        </div>
      </div>
      <aside className="detail-side">
        <div className="risk-box">
          {plan.risk_assessment.risk_items.map((risk) => (
            <p key={risk.risk_id}><AlertTriangle size={16} />{risk.title}: {risk.message}</p>
          ))}
        </div>
        <div className="option-groups">
          {plan.segments.map((segment, index) => {
            const expanded = Boolean(expandedSegments[segment.segment_id]);
            const transferOption = segment.segment_type === "LOCAL_TRANSFER" ? selectedTransferOption(segment) : null;
            const railSeat = segment.segment_type === "RAIL" ? selectedRailSeat(segment) : null;
            const flightCabin = segment.segment_type === "FLIGHT" ? selectedFlightCabin(segment) : null;
            return (
              <div key={segment.segment_id} className="option-group">
                <div className="option-group-title">
                  <div>
                    <span>第 {index + 1} 段</span>
                    <strong>{segmentTitle(segment)}</strong>
                  </div>
                  <button className="expand-button" type="button" title={expanded ? "收起详情" : "展开详情"} onClick={() => toggleSegment(segment.segment_id)}>
                    {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                  </button>
                </div>
                <div className="selected-option-summary">
                  {transferOption && (
                    <>
                      <div>
                        <strong>{transferOption.label}</strong>
                        <span>{formatMoney(transferOption.estimated_cost)} · {minutesToText(transferOption.duration_minutes)}</span>
                      </div>
                      <TransferRouteSummary option={transferOption} />
                    </>
                  )}
                  {railSeat && (
                    <div>
                      <strong>{railSeat.seat_type}</strong>
                      <span>{formatMoney(railSeat.price)}</span>
                    </div>
                  )}
                  {flightCabin && (
                    <div>
                      <strong>{flightCabin.cabin_type}</strong>
                      <span>{formatMoney(flightCabin.price)}</span>
                    </div>
                  )}
                </div>
                {expanded && (
                  <div className="option-detail-panel">
                    {segment.seat_options && (
                      <div className="option-buttons">
                        {segment.seat_options.map((option) => (
                          <button key={option.option_id} disabled={busy || option.option_id === segment.selected_seat_option_id} onClick={() => applyOption(segment, "RAIL_SEAT", option.option_id, option.seat_type)}>
                            {option.seat_type} {formatMoney(option.price)}
                          </button>
                        ))}
                      </div>
                    )}
                    {segment.cabin_options && (
                      <div className="option-buttons">
                        {segment.cabin_options.map((option) => (
                          <button key={option.option_id} disabled={busy || option.option_id === segment.selected_cabin_option_id} onClick={() => applyOption(segment, "FLIGHT_CABIN", option.option_id, option.cabin_type)}>
                            {option.cabin_type} {formatMoney(option.price)}
                          </button>
                        ))}
                      </div>
                    )}
                    {segment.segment_type === "LOCAL_TRANSFER" && (
                      <div className="transfer-option-list">
                        {transferOptionsFor(segment).map((option) => (
                          <div className={option.option_id === segment.option_id ? "transfer-option selected" : "transfer-option"} key={option.option_id}>
                            <button disabled={busy || option.option_id === segment.option_id} onClick={() => applyOption(segment, "LOCAL_TRANSFER", option.option_id, option.label)}>
                              {option.label}
                              <span>{formatMoney(option.estimated_cost)} · {minutesToText(option.duration_minutes)}</span>
                            </button>
                            <TransferRouteSummary option={option} detailed />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        {message && <p className="inline-message">{message}</p>}
      </aside>
    </section>
  );
}

export default function App() {
  const [rawInput, setRawInput] = useState(SAMPLE_INPUT);
  const [response, setResponse] = useState<TravelPlanResponse | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedPlan = useMemo(() => {
    const explicit = findPlan(response, selectedPlanId);
    if (explicit) return explicit;
    return findPlan(response, preferredRecommendationPlanId(response));
  }, [response, selectedPlanId]);

  const themeClass = useMemo(() => destinationThemeClass(response), [response]);
  const destinationLabel = useMemo(() => destinationDisplayName(response), [response]);
  const recommendedPlanIds = useMemo(() => new Set(response?.recommendation_result?.recommendations.map((slot) => slot.plan_id).filter(Boolean) ?? []), [response]);
  const candidatePlans = useMemo(() => response?.plans.filter((plan) => !recommendedPlanIds.has(plan.plan_id)) ?? [], [response, recommendedPlanIds]);

  async function submit() {
    setLoading(true);
    setError("");
    try {
      const result = await planTrip(rawInput);
      setResponse(result);
      setSelectedPlanId(preferredRecommendationPlanId(result));
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
    <main className={themeClass ? `app-shell ${themeClass}` : "app-shell"}>
      <div className="destination-backdrop" aria-hidden="true" data-destination={destinationLabel}>
        <span className="landmark primary" />
        <span className="landmark secondary" />
        <span className="landmark line" />
        <span className="landmark terrain" />
      </div>
      <section className="topbar">
        <div>
          <h1>AI 出行规划器</h1>
          <p>Mock DEV / TEST · Schema 1.15 · REDIRECT_ONLY</p>
        </div>
      </section>

      <section className="query-panel">
        <textarea value={rawInput} onChange={(event) => setRawInput(event.target.value)} />
        <button className="submit-button" onClick={submit} disabled={loading}>
          {loading ? <RefreshCw className="spin" size={18} /> : <Search size={18} />}
          {loading ? "规划中" : "开始规划"}
        </button>
      </section>

      {error && <section className="error-panel">{error}</section>}

      {response && (
        <>
          <section className="recommendation-grid">
            {response.recommendation_result?.recommendations.map((slot) => (
              <RecommendationCard key={slot.recommendation_type} slot={slot} plan={findPlan(response, slot.plan_id)} selected={slot.plan_id === selectedPlan?.plan_id} onSelect={(plan) => setSelectedPlanId(plan.plan_id)} />
            ))}
          </section>

          {selectedPlan && <DetailPanel plan={selectedPlan} onRecalculated={replacePlan} />}

          <section className="candidate-list">
            <div className="section-heading"><h2>候选方案</h2></div>
            {candidatePlans.map((plan) => (
              <button key={plan.plan_id} className={plan.plan_id === selectedPlan?.plan_id ? "candidate active" : "candidate"} onClick={() => setSelectedPlanId(plan.plan_id)}>
                <span className="candidate-title">
                  {planDisplayName(plan)}
                  <small>{planTypeLabel(plan.plan_type)} · {riskLabel(plan.risk_assessment.overall_risk_level)}</small>
                </span>
                <strong>{formatMoney(plan.cost_breakdown.total_cost)}</strong>
                {!plan.can_be_selected_by_llm && <em>{plan.risk_assessment.overall_risk_level === "BLOCKED" ? "BLOCKED" : "备选"} · {plan.block_reason_message ?? "不进入主推荐"}</em>}
              </button>
            ))}
          </section>

        </>
      )}
    </main>
  );
}
