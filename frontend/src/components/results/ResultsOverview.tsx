import type { ImageSourcePropType } from "react-native";
import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";
import type { RecommendationSlot, TravelPlan, TravelPlanResponse } from "../../types";
import { formatMoney, minutesToText, riskLabel } from "../../utils/format";
import { PlanSelector } from "./PlanSelector";
import { RecommendationRationale } from "./RecommendationRationale";
import { ResultsHeader } from "./ResultsHeader";
import { RouteSummaryHero } from "./RouteSummaryHero";
import { RouteTimeline } from "./RouteTimeline";

type Props = {
  response: TravelPlanResponse;
  plan: TravelPlan;
  recommendations: RecommendationSlot[];
  candidatePlans: TravelPlan[];
  imageSource?: ImageSourcePropType;
  busy: boolean;
  schedulePanel?: ReactNode;
  onSelectRecommendation: (plan: TravelPlan, slot: RecommendationSlot) => void;
  onSelectCandidate: (plan: TravelPlan) => void;
  onSources: () => void;
  onRetrySources: () => void;
};

function DataStatus({ response, busy, onRetry }: { response: TravelPlanResponse; busy: boolean; onRetry: () => void }) {
  const warnings = response.user_visible_warnings.slice(0, 1);
  const failures = response.source_failures.slice(0, 1);
  const hiddenMessageCount = Math.max(0, response.user_visible_warnings.length - warnings.length) + Math.max(0, response.source_failures.length - failures.length);
  if (!response.user_visible_warnings.length && !response.missing_components.length && !failures.length) return null;
  return (
    <View style={styles.status}>
      <Text style={styles.statusTitle}>{response.planning_status === "PARTIAL" ? "部分数据暂不可用" : "数据状态"}</Text>
      {warnings.map((warning) => <Text key={warning} style={styles.statusBody}>{warning}</Text>)}
      {response.missing_components.length ? <Text style={styles.statusMeta}>缺失：{response.missing_components.join("、")}</Text> : null}
      {failures.map((failure) => <Text key={failure.failure_id} style={styles.statusMeta}>{failure.user_visible_message}</Text>)}
      {hiddenMessageCount ? <Text style={styles.statusMeta}>另有 {hiddenMessageCount} 条数据说明，可在“数据来源”中查看。</Text> : null}
      {response.async_job && failures.length ? <Pressable accessibilityRole="button" accessibilityLabel="重试失败的数据来源" disabled={busy} onPress={onRetry} style={({ pressed }) => [styles.retry, pressed && styles.pressed, busy && styles.disabled]}><Text style={styles.retryText}>{busy ? "重试中" : "重试来源"}</Text></Pressable> : null}
    </View>
  );
}

function ResultsSkeleton() {
  return (
    <View accessibilityLabel="正在更新路线" style={styles.skeleton}>
      <View style={[styles.skeletonBar, styles.skeletonWide]} />
      <View style={[styles.skeletonBar, styles.skeletonMedium]} />
      <View style={[styles.skeletonBar, styles.skeletonWide]} />
    </View>
  );
}

export function ResultsOverview({ response, plan, recommendations, candidatePlans, imageSource, busy, schedulePanel, onSelectRecommendation, onSelectCandidate, onSources, onRetrySources }: Props) {
  return (
    <View style={styles.page}>
      <ResultsHeader request={response.travel_request} plan={plan} onSources={onSources} />
      <RouteSummaryHero destinationName={response.destination_presentation?.display_name} imageSource={imageSource} plan={plan} request={response.travel_request} />
      <View style={styles.sectionHead}>
        <Text accessibilityRole="header" style={styles.heading}>选择方案</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="查看数据来源" hitSlop={ui.hitSlop} onPress={onSources} style={({ pressed }) => pressed && styles.pressed}><Text style={styles.sectionLink}>数据来源</Text></Pressable>
      </View>
      <PlanSelector onSelect={onSelectRecommendation} plans={response.plans} recommendations={recommendations} selectedPlanId={plan.plan_id} />
      <RecommendationRationale partial={response.planning_status === "PARTIAL"} plan={plan} plans={response.plans} recommendations={recommendations} />
      {schedulePanel}
      <RouteTimeline plan={plan} />
      <DataStatus busy={busy} onRetry={onRetrySources} response={response} />
      {candidatePlans.length ? (
        <View>
          <Text accessibilityRole="header" style={styles.heading}>其他可用方案</Text>
          {candidatePlans.map((candidate) => (
            <Pressable accessibilityRole="button" accessibilityLabel={`切换到${candidate.plan_name}`} key={candidate.plan_id} onPress={() => onSelectCandidate(candidate)} style={({ pressed }) => [styles.candidate, candidate.plan_id === plan.plan_id && styles.candidateSelected, pressed && styles.pressed]}>
              <View style={styles.candidateCopy}><Text style={styles.candidateTitle}>{candidate.plan_name || "候选方案"}</Text><Text style={styles.statusMeta}>{minutesToText(candidate.total_duration_minutes)} · {riskLabel(candidate.risk_assessment.overall_risk_level)}</Text></View>
              <Text style={styles.candidateCost}>{formatMoney(candidate.cost_breakdown.total_cost)}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {busy ? <ResultsSkeleton /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: ui.spacing.md, paddingBottom: ui.spacing.xl, position: "relative" },
  sectionHead: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", marginBottom: -ui.spacing.xs, marginTop: ui.spacing.xxs, minHeight: 36 },
  sectionLink: { color: ui.colors.primary, fontSize: 12, fontWeight: "800" },
  status: { backgroundColor: ui.colors.warningSurface, borderRadius: ui.radius.card, gap: ui.spacing.xs, padding: ui.spacing.md },
  statusTitle: { color: ui.colors.warning, fontSize: 14, fontWeight: "800", lineHeight: 19 },
  statusBody: { color: ui.colors.text, fontSize: 13, lineHeight: 19 },
  statusMeta: { color: ui.colors.textSecondary, fontSize: 12, lineHeight: 18 },
  retry: { alignItems: "center", alignSelf: "flex-start", backgroundColor: ui.colors.surface, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  retryText: { color: ui.colors.primaryDeep, fontSize: 13, fontWeight: "800" },
  heading: { color: ui.colors.text, fontSize: 16, fontWeight: "800", lineHeight: 21 },
  candidate: { alignItems: "center", borderBottomColor: ui.colors.line, borderBottomWidth: StyleSheet.hairlineWidth, flexDirection: "row", minHeight: 64, paddingVertical: ui.spacing.sm },
  candidateSelected: { backgroundColor: ui.colors.primarySoft },
  candidateCopy: { flex: 1, paddingHorizontal: ui.spacing.sm },
  candidateTitle: { color: ui.colors.text, fontSize: 14, fontWeight: "800", lineHeight: 19 },
  candidateCost: { color: ui.colors.primaryDeep, fontSize: 14, fontWeight: "800", paddingHorizontal: ui.spacing.sm },
  skeleton: { backgroundColor: "rgba(239,244,243,0.94)", borderRadius: ui.radius.card, gap: ui.spacing.md, left: 0, padding: ui.spacing.lg, position: "absolute", right: 0, top: 236 },
  skeletonBar: { backgroundColor: ui.colors.disabled, borderRadius: ui.radius.small, height: 44 },
  skeletonWide: { width: "100%" },
  skeletonMedium: { width: "72%" },
  pressed: { opacity: 0.78, transform: [{ scale: 0.98 }] },
  disabled: { backgroundColor: ui.colors.disabled }
});
