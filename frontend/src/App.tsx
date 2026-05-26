import { AlertTriangle, Clock, Database, ExternalLink, Plane, RefreshCw, Search, ShieldCheck, Train, WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { bookingRedirect, loadDataSources, planTrip, recalculate } from "./api/client";
import type { DataSourceStatusResponse, RecommendationSlot, Segment, TravelPlan, TravelPlanResponse } from "./types";
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

function RecommendationCard({ slot, plan, onSelect }: { slot: RecommendationSlot; plan: TravelPlan | null; onSelect: (plan: TravelPlan) => void }) {
  return (
    <section className="card recommendation-card">
      <div className="card-topline">
        <span className="eyebrow">{slotLabel(slot.recommendation_type)}</span>
        <span className={`risk ${plan?.risk_assessment.overall_risk_level ?? slot.status}`}>{plan ? riskLabel(plan.risk_assessment.overall_risk_level) : slot.status}</span>
      </div>
      {plan ? (
        <>
          <h2>{plan.plan_name}</h2>
          <div className="metric-row">
            <span><WalletCards size={16} />{formatMoney(plan.cost_breakdown.total_cost)}</span>
            <span><Clock size={16} />{minutesToText(plan.total_duration_minutes)}</span>
            <span><ShieldCheck size={16} />{plan.comfort_score.total_score.toFixed(1)} / 10</span>
          </div>
          <p>{slot.reason}</p>
          <button className="primary-action" onClick={() => onSelect(plan)}>查看详情</button>
        </>
      ) : (
        <>
          <h2>{slot.status}</h2>
          <p>{slot.reason}</p>
        </>
      )}
    </section>
  );
}

function SegmentTimeline({ segments }: { segments: Segment[] }) {
  return (
    <div className="timeline">
      {segments.map((segment) => (
        <div className="timeline-row" key={segment.segment_id}>
          <span className="timeline-icon"><SegmentIcon type={segment.segment_type} /></span>
          <div>
            <strong>
              {segment.segment_type === "RAIL" && `${segment.train_number} ${segment.origin_station} → ${segment.destination_station}`}
              {segment.segment_type === "FLIGHT" && `${segment.flight_number} ${segment.origin_airport} → ${segment.destination_airport}`}
              {segment.segment_type === "LOCAL_TRANSFER" && `${segment.transfer_mode} ${segment.origin} → ${segment.destination}`}
            </strong>
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
          <h2>{plan.plan_name}</h2>
          <button title="生成跳转" className="icon-button" onClick={openRedirect} disabled={busy}><ExternalLink size={18} /></button>
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
        <h3 className="subheading">数据来源</h3>
        <div className="source-chips">
          {plan.data_sources.map((source) => (
            <span key={source.source_id}>{source.source_name} · {source.source_type}</span>
          ))}
        </div>
      </div>
      <aside className="detail-side">
        <div className="score-block">
          <span>舒适度</span>
          <strong>{plan.comfort_score.total_score.toFixed(1)} / 10</strong>
          <p>{plan.comfort_score.explanation}</p>
        </div>
        <div className="breakdown">
          {Object.entries(plan.comfort_score.breakdown).map(([key, value]) => (
            <div key={key}>
              <span>{key}</span>
              <meter min="0" max="10" value={value} />
            </div>
          ))}
        </div>
        <div className="risk-box">
          {plan.risk_assessment.risk_items.map((risk) => (
            <p key={risk.risk_id}><AlertTriangle size={16} />{risk.title}: {risk.message}</p>
          ))}
        </div>
        <div className="option-groups">
          {plan.segments.map((segment) => (
            <div key={segment.segment_id} className="option-group">
              {segment.seat_options?.map((option) => (
                <button key={option.option_id} disabled={busy || option.option_id === segment.selected_seat_option_id} onClick={() => applyOption(segment, "RAIL_SEAT", option.option_id, option.seat_type)}>
                  {option.seat_type} {formatMoney(option.price)}
                </button>
              ))}
              {segment.cabin_options?.map((option) => (
                <button key={option.option_id} disabled={busy || option.option_id === segment.selected_cabin_option_id} onClick={() => applyOption(segment, "FLIGHT_CABIN", option.option_id, option.cabin_type)}>
                  {option.cabin_type} {formatMoney(option.price)}
                </button>
              ))}
              {segment.segment_type === "LOCAL_TRANSFER" && segment.available_options?.map((option) => (
                <button key={option} disabled={busy || option === segment.option_id} onClick={() => applyOption(segment, "LOCAL_TRANSFER", option, option)}>
                  {option.replace("transfer_", "")}
                </button>
              ))}
            </div>
          ))}
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
  const [dataSources, setDataSources] = useState<DataSourceStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    loadDataSources().then(setDataSources).catch(() => undefined);
  }, []);

  const selectedPlan = useMemo(() => {
    const explicit = findPlan(response, selectedPlanId);
    if (explicit) return explicit;
    const firstRecommended = response?.recommendation_result?.recommendations.find((slot) => slot.plan_id)?.plan_id ?? null;
    return findPlan(response, firstRecommended);
  }, [response, selectedPlanId]);

  async function submit() {
    setLoading(true);
    setError("");
    try {
      const result = await planTrip(rawInput);
      setResponse(result);
      setSelectedPlanId(result.recommendation_result?.recommendations.find((slot) => slot.plan_id)?.plan_id ?? null);
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
    <main>
      <section className="topbar">
        <div>
          <h1>AI 出行规划器</h1>
          <p>Mock DEV / TEST · Schema 1.15 · REDIRECT_ONLY</p>
        </div>
        <button className="icon-button" title="刷新数据源状态" onClick={() => loadDataSources().then(setDataSources)}><Database size={20} /></button>
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
          <section className="status-strip">
            <span>{response.travel_request.origin_text} → {response.travel_request.destination_text}</span>
            <span>{response.planning_status} · {response.progress}%</span>
            <span>trace {response.trace_id}</span>
          </section>

          <section className="recommendation-grid">
            {response.recommendation_result?.recommendations.map((slot) => (
              <RecommendationCard key={slot.recommendation_type} slot={slot} plan={findPlan(response, slot.plan_id)} onSelect={(plan) => setSelectedPlanId(plan.plan_id)} />
            ))}
          </section>

          {response.user_visible_warnings.length > 0 && (
            <section className="notice-row">
              {response.user_visible_warnings.map((warning) => <span key={warning}>{warning}</span>)}
            </section>
          )}

          {selectedPlan && <DetailPanel plan={selectedPlan} onRecalculated={replacePlan} />}

          <section className="candidate-list">
            <div className="section-heading"><h2>候选方案</h2></div>
            {response.plans.map((plan) => (
              <button key={plan.plan_id} className={plan.plan_id === selectedPlan?.plan_id ? "candidate active" : "candidate"} onClick={() => setSelectedPlanId(plan.plan_id)}>
                <span>{plan.plan_name}</span>
                <strong>{formatMoney(plan.cost_breakdown.total_cost)}</strong>
                {!plan.can_be_selected_by_llm && <em>{plan.risk_assessment.overall_risk_level === "BLOCKED" ? "BLOCKED" : "备选"} · {plan.block_reason_message ?? "不进入主推荐"}</em>}
              </button>
            ))}
          </section>

          {response.plans.some((plan) => !plan.can_be_selected_by_llm) && (
            <section className="blocked-panel">
              <h2>备选与阻断说明</h2>
              {response.plans.filter((plan) => !plan.can_be_selected_by_llm).map((plan) => (
                <p key={plan.plan_id}>
                  <strong>{plan.plan_name}</strong>
                  <span>{plan.block_reason_message ?? "该方案不进入三张主推荐卡。"}</span>
                </p>
              ))}
            </section>
          )}

          {response.source_failures.length > 0 && (
            <section className="source-failures">
              <h2>数据缺失</h2>
              {response.source_failures.map((failure) => <p key={failure.failure_id}>{failure.user_visible_message}</p>)}
            </section>
          )}
        </>
      )}

      <section className="data-sources">
        <h2>数据源状态</h2>
        <div>
          {dataSources?.sources.map((source) => (
            <span key={source.source_id}>{source.source_name}: {source.status}</span>
          ))}
        </div>
      </section>
    </main>
  );
}
