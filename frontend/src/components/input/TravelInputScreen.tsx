import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View
} from "react-native";
import { ui } from "../../designSystem";
import type {
  RecentPlanSnapshot,
  RetentionPreferences
} from "../../nativeCapabilities";
import { minutesToText } from "../../utils/format";

type Props = {
  rawInput: string;
  loading: boolean;
  error: string;
  recentPlans: RecentPlanSnapshot[];
  favoritePlans: RecentPlanSnapshot[];
  retentionPreferences: RetentionPreferences;
  commonOriginDraft: string;
  destinationPreferenceDraft: string;
  wideLayout: boolean;
  onChangeInput: (value: string) => void;
  onChangeCommonOrigin: (value: string) => void;
  onChangeDestinationPreference: (value: string) => void;
  onSubmit: () => void;
  onLocation: () => void;
  onAppendTomorrow: () => void;
  onAppendLessTransfers: () => void;
  onOpenStoredPlan: (plan: RecentPlanSnapshot) => void;
  onApplyCommonOrigin: () => void;
  onSavePreferences: (
    nextEnabled: Partial<{
      common_origin_enabled: boolean;
      destination_preferences_enabled: boolean;
    }>
  ) => void;
};

function PlanRow({
  plan,
  onPress
}: {
  plan: RecentPlanSnapshot;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityLabel={`查看历史规划：${plan.origin_text}到${plan.destination_text}`}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.planRow, pressed && styles.pressed]}
    >
      <View style={styles.planCopy}>
        <Text numberOfLines={1} style={styles.planTitle}>
          {plan.origin_text} → {plan.destination_text}
        </Text>
        <Text style={styles.planMeta}>
          {plan.travel_date} · 脱敏摘要 · {minutesToText(plan.total_duration_minutes)}
        </Text>
      </View>
      <Text numberOfLines={1} style={styles.planPrice}>{plan.total_cost_text}</Text>
    </Pressable>
  );
}

export function TravelInputScreen({
  rawInput,
  loading,
  error,
  recentPlans,
  favoritePlans,
  retentionPreferences,
  commonOriginDraft,
  destinationPreferenceDraft,
  wideLayout,
  onChangeInput,
  onChangeCommonOrigin,
  onChangeDestinationPreference,
  onSubmit,
  onLocation,
  onAppendTomorrow,
  onAppendLessTransfers,
  onOpenStoredPlan,
  onApplyCommonOrigin,
  onSavePreferences
}: Props) {
  const inputRef = useRef<TextInput>(null);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (error && !rawInput.trim()) inputRef.current?.focus();
  }, [error, rawInput]);

  const visibleRecentPlans = showAll ? recentPlans : recentPlans.slice(0, 2);

  return (
    <>
      <ScrollView
        contentContainerStyle={[styles.content, wideLayout && styles.contentWide]}
        keyboardShouldPersistTaps="handled"
        style={styles.screen}
      >
        <View style={styles.header}>
          <Text style={styles.brand}>出行搭子</Text>
          <Pressable
            accessibilityLabel="打开出行偏好"
            accessibilityRole="button"
            onPress={() => setPreferencesOpen(true)}
            style={({ pressed }) => [styles.headerAction, pressed && styles.pressed]}
          >
            <Text style={styles.headerActionText}>偏好</Text>
          </Pressable>
        </View>

        <View style={styles.hero}>
          <Text accessibilityRole="header" style={styles.title}>今天，想去哪里？</Text>
          <Text style={styles.subtitle}>一句话告诉我出发地、目的地和时间。</Text>
        </View>

        <View style={styles.composer}>
          <Text style={styles.fieldLabel}>描述你的行程</Text>
          <TextInput
            accessibilityLabel="描述你的行程"
            multiline
            onChangeText={onChangeInput}
            placeholder="例如：明早 8 点从上海出发去青岛，希望少换乘。"
            placeholderTextColor={ui.colors.textSecondary}
            ref={inputRef}
            style={styles.input}
            textAlignVertical="top"
            value={rawInput}
          />
          <View style={styles.quickActions}>
            <Pressable accessibilityLabel="使用定位填写出发地" accessibilityRole="button" onPress={onLocation} style={({ pressed }) => [styles.quickAction, pressed && styles.pressed]}>
              <Text style={styles.quickActionText}>使用定位</Text>
            </Pressable>
            <Pressable accessibilityLabel="在行程中加入明天出发" accessibilityRole="button" onPress={onAppendTomorrow} style={({ pressed }) => [styles.quickAction, pressed && styles.pressed]}>
              <Text style={styles.quickActionText}>明天出发</Text>
            </Pressable>
            <Pressable accessibilityLabel="在行程中加入少换乘偏好" accessibilityRole="button" onPress={onAppendLessTransfers} style={({ pressed }) => [styles.quickAction, pressed && styles.pressed]}>
              <Text style={styles.quickActionText}>少换乘</Text>
            </Pressable>
          </View>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <Pressable
            accessibilityLabel="开始规划出行方案"
            accessibilityRole="button"
            accessibilityState={{ disabled: loading }}
            disabled={loading}
            onPress={onSubmit}
            style={({ pressed }) => [
              styles.submit,
              pressed && !loading && styles.pressed,
              loading && styles.submitDisabled
            ]}
          >
            {loading ? <ActivityIndicator color={ui.colors.surface} /> : <Text style={styles.submitText}>开始规划</Text>}
          </Pressable>
        </View>

        <View style={styles.sectionHeader}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>最近规划</Text>
          <Pressable accessibilityLabel={showAll ? "收起历史与收藏" : "查看全部历史与收藏"} accessibilityRole="button" onPress={() => setShowAll((current) => !current)}>
            <Text style={styles.textAction}>{showAll ? "收起" : "查看全部"}</Text>
          </Pressable>
        </View>
        <View style={styles.planList}>
          {visibleRecentPlans.length ? visibleRecentPlans.map((plan) => (
            <PlanRow key={`recent-${plan.plan_id}`} onPress={() => onOpenStoredPlan(plan)} plan={plan} />
          )) : (
            <Text style={styles.emptyText}>完成一次规划后，会在这里保存脱敏摘要。</Text>
          )}
        </View>

        {showAll ? (
          <>
            <View style={styles.sectionHeader}>
              <Text accessibilityRole="header" style={styles.sectionTitle}>收藏方案</Text>
            </View>
            <View style={styles.planList}>
              {favoritePlans.length ? favoritePlans.map((plan) => (
                <PlanRow key={`favorite-${plan.plan_id}`} onPress={() => onOpenStoredPlan(plan)} plan={plan} />
              )) : <Text style={styles.emptyText}>收藏路线后会显示在这里。</Text>}
            </View>
          </>
        ) : null}
      </ScrollView>

      <Modal
        animationType="slide"
        onRequestClose={() => setPreferencesOpen(false)}
        transparent
        visible={preferencesOpen}
      >
        <View style={styles.modalOverlay}>
          <Pressable accessibilityLabel="关闭偏好设置" accessibilityRole="button" onPress={() => setPreferencesOpen(false)} style={styles.modalBackdrop} />
          <View style={styles.sheet}>
            <View style={styles.sheetHeader}>
              <View style={styles.planCopy}>
                <Text accessibilityRole="header" style={styles.sheetTitle}>出行偏好</Text>
                <Text style={styles.sheetCopy}>只在你开启后保存；关闭会清空对应内容。</Text>
              </View>
              <Pressable accessibilityLabel="关闭偏好设置" accessibilityRole="button" onPress={() => setPreferencesOpen(false)} style={styles.closeButton}>
                <Text style={styles.headerActionText}>完成</Text>
              </Pressable>
            </View>

            <Text style={styles.fieldLabel}>常用出发地</Text>
            <TextInput
              accessibilityLabel="常用出发地"
              onChangeText={onChangeCommonOrigin}
              placeholder="例如：上海虹桥"
              placeholderTextColor={ui.colors.textSecondary}
              style={styles.preferenceInput}
              value={commonOriginDraft}
            />
            <View style={styles.preferenceActions}>
              <Pressable
                accessibilityLabel="常用出发地记忆开关"
                accessibilityRole="switch"
                accessibilityState={{ checked: retentionPreferences.common_origin_enabled }}
                onPress={() => onSavePreferences({ common_origin_enabled: !retentionPreferences.common_origin_enabled })}
                style={[styles.preferenceButton, retentionPreferences.common_origin_enabled && styles.preferenceButtonActive]}
              >
                <Text style={styles.preferenceButtonText}>{retentionPreferences.common_origin_enabled ? "关闭记忆" : "开启记忆"}</Text>
              </Pressable>
              {retentionPreferences.common_origin_enabled && retentionPreferences.common_origin_text ? (
                <Pressable accessibilityLabel="套用常用出发地" accessibilityRole="button" onPress={onApplyCommonOrigin} style={styles.preferenceButton}>
                  <Text style={styles.preferenceButtonText}>套用</Text>
                </Pressable>
              ) : null}
            </View>

            <Text style={[styles.fieldLabel, styles.preferenceLabel]}>目的地偏好</Text>
            <TextInput
              accessibilityLabel="目的地偏好"
              onChangeText={onChangeDestinationPreference}
              placeholder="用顿号或逗号分隔"
              placeholderTextColor={ui.colors.textSecondary}
              style={styles.preferenceInput}
              value={destinationPreferenceDraft}
            />
            <View style={styles.preferenceActions}>
              <Pressable
                accessibilityLabel="目的地偏好记忆开关"
                accessibilityRole="switch"
                accessibilityState={{ checked: retentionPreferences.destination_preferences_enabled }}
                onPress={() => onSavePreferences({ destination_preferences_enabled: !retentionPreferences.destination_preferences_enabled })}
                style={[styles.preferenceButton, retentionPreferences.destination_preferences_enabled && styles.preferenceButtonActive]}
              >
                <Text style={styles.preferenceButtonText}>{retentionPreferences.destination_preferences_enabled ? "关闭记忆" : "开启记忆"}</Text>
              </Pressable>
              <Pressable accessibilityLabel="保存当前偏好" accessibilityRole="button" onPress={() => onSavePreferences({})} style={styles.saveButton}>
                <Text style={styles.saveButtonText}>保存偏好</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingBottom: 96, paddingHorizontal: ui.spacing.lg },
  contentWide: { alignSelf: "center", maxWidth: ui.contentMaxWidth, width: "100%" },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", minHeight: 64 },
  brand: { color: ui.colors.primaryDeep, fontSize: 16, fontWeight: "800" },
  headerAction: { alignItems: "center", backgroundColor: ui.colors.surface, borderRadius: ui.radius.control, justifyContent: "center", minHeight: 44, minWidth: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  headerActionText: { color: ui.colors.primaryDeep, fontSize: 12, fontWeight: "800" },
  hero: { paddingBottom: 18, paddingTop: ui.spacing.sm },
  title: { color: ui.colors.text, fontSize: 29, fontWeight: "800", letterSpacing: -0.8, lineHeight: 35 },
  subtitle: { color: ui.colors.textSecondary, fontSize: 13, lineHeight: 20, marginTop: ui.spacing.xs },
  composer: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, padding: 15 },
  fieldLabel: { color: ui.colors.primaryDeep, fontSize: 12, fontWeight: "800", lineHeight: 18, marginBottom: ui.spacing.sm },
  input: { backgroundColor: ui.colors.background, borderRadius: ui.radius.control, color: ui.colors.text, fontSize: 14, lineHeight: 22, minHeight: 118, padding: 13 },
  quickActions: { flexDirection: "row", gap: ui.spacing.sm, marginTop: 10 },
  quickAction: { alignItems: "center", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, flex: 1, justifyContent: "center", minHeight: 40, minWidth: 0, paddingHorizontal: ui.spacing.xxs },
  quickActionText: { color: ui.colors.primaryDeep, fontSize: 11, fontWeight: "800" },
  error: { color: ui.colors.danger, fontSize: 12, lineHeight: 18, marginTop: ui.spacing.sm },
  submit: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: ui.radius.control, justifyContent: "center", marginTop: ui.spacing.md, minHeight: ui.touchTarget },
  submitDisabled: { backgroundColor: ui.colors.disabled },
  submitText: { color: ui.colors.surface, fontSize: 14, fontWeight: "800" },
  sectionHeader: { alignItems: "baseline", flexDirection: "row", justifyContent: "space-between", marginBottom: 9, marginTop: 20 },
  sectionTitle: { color: ui.colors.text, fontSize: 16, fontWeight: "800", lineHeight: 22 },
  textAction: { color: ui.colors.primary, fontSize: 11, fontWeight: "800", lineHeight: 16 },
  planList: { backgroundColor: ui.colors.surface, borderRadius: ui.radius.card, overflow: "hidden" },
  planRow: { alignItems: "center", borderBottomColor: ui.colors.line, borderBottomWidth: StyleSheet.hairlineWidth, flexDirection: "row", gap: ui.spacing.md, minHeight: 72, paddingHorizontal: 14, paddingVertical: ui.spacing.md },
  planCopy: { flex: 1, minWidth: 0 },
  planTitle: { color: ui.colors.text, fontSize: 13, fontWeight: "800", lineHeight: 18 },
  planMeta: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 15, marginTop: 3 },
  planPrice: { color: ui.colors.primaryDeep, flexShrink: 0, fontSize: 14, fontWeight: "800" },
  emptyText: { color: ui.colors.textSecondary, fontSize: 12, lineHeight: 18, padding: ui.spacing.lg },
  pressed: { opacity: 0.78, transform: [{ scale: 0.98 }] },
  modalOverlay: { flex: 1, justifyContent: "flex-end" },
  modalBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(21,40,43,0.36)" },
  sheet: { backgroundColor: ui.colors.surface, borderTopLeftRadius: ui.radius.card, borderTopRightRadius: ui.radius.card, paddingBottom: 32, paddingHorizontal: ui.spacing.lg, paddingTop: ui.spacing.lg },
  sheetHeader: { alignItems: "center", flexDirection: "row", gap: ui.spacing.md, marginBottom: ui.spacing.xl },
  sheetTitle: { color: ui.colors.text, fontSize: 20, fontWeight: "800", lineHeight: 24 },
  sheetCopy: { color: ui.colors.textSecondary, fontSize: 11, lineHeight: 16, marginTop: 3 },
  closeButton: { alignItems: "center", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, justifyContent: "center", minHeight: 44, paddingHorizontal: ui.spacing.md },
  preferenceInput: { backgroundColor: ui.colors.background, borderRadius: ui.radius.control, color: ui.colors.text, fontSize: 13, minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  preferenceLabel: { marginTop: ui.spacing.lg },
  preferenceActions: { flexDirection: "row", gap: ui.spacing.sm, marginTop: ui.spacing.sm },
  preferenceButton: { alignItems: "center", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  preferenceButtonActive: { backgroundColor: ui.colors.connection },
  preferenceButtonText: { color: ui.colors.primaryDeep, fontSize: 12, fontWeight: "800" },
  saveButton: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: ui.radius.control, flex: 1, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  saveButtonText: { color: ui.colors.surface, fontSize: 13, fontWeight: "800" }
});
