import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, Easing, Image, Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Defs, LinearGradient as SvgLinearGradient, RadialGradient, Rect, Stop } from "react-native-svg";
import worldMapFlowImage from "../../../assets/maps/world-map-flow.png";
import worldMapImage from "../../../assets/maps/world-map.png";
import { ui } from "../../designSystem";
import { buildPlanningStagePresentation } from "../../utils/routePlanning";
import { PlanningStageList } from "./PlanningStageList";

type Props = {
  progress: number;
  candidateCount?: number;
  originText?: string;
  destinationText?: string;
  onCancel?: () => void;
  cancelBusy?: boolean;
};

function PlanningBackground() {
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Svg height="100%" width="100%">
        <Defs>
          <SvgLinearGradient id="planningSurface" x1="0%" x2="0%" y1="0%" y2="100%">
            <Stop offset="0%" stopColor={ui.colors.planningBackgroundStart} />
            <Stop offset="100%" stopColor={ui.colors.planningBackgroundEnd} />
          </SvgLinearGradient>
          <RadialGradient id="planningAmbient" cx="76%" cy="18%" r="28%">
            <Stop offset="0%" stopColor={ui.colors.planningAmbient} stopOpacity={0.22} />
            <Stop offset="100%" stopColor={ui.colors.planningAmbient} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect fill="url(#planningSurface)" height="100%" width="100%" />
        <Rect fill="url(#planningAmbient)" height="100%" width="100%" />
      </Svg>
    </View>
  );
}

function MapSweep() {
  return (
    <Svg height="100%" width="100%">
      <Defs>
        <SvgLinearGradient id="mapSweep" x1="0%" x2="100%" y1="0%" y2="0%">
          <Stop offset="0%" stopColor={ui.colors.mapGlow} stopOpacity={0} />
          <Stop offset="50%" stopColor={ui.colors.mapGlow} stopOpacity={0.22} />
          <Stop offset="100%" stopColor={ui.colors.mapGlow} stopOpacity={0} />
        </SvgLinearGradient>
      </Defs>
      <Rect fill="url(#mapSweep)" height="100%" width="100%" />
    </Svg>
  );
}

export function PlanningProgressScreen({ progress, candidateCount = 0, originText, destinationText, onCancel, cancelBusy = false }: Props) {
  const normalizedProgress = Math.max(0, Math.min(100, Math.round(progress)));
  const stagePresentation = buildPlanningStagePresentation(normalizedProgress);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [mapWidth, setMapWidth] = useState(0);
  const animatedProgress = useRef(new Animated.Value(normalizedProgress)).current;

  useEffect(() => {
    void AccessibilityInfo.isReduceMotionEnabled().then(setReduceMotion);
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduceMotion);
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    animatedProgress.stopAnimation();
    if (reduceMotion) {
      animatedProgress.setValue(normalizedProgress);
      return;
    }
    const target = normalizedProgress >= 100 ? 100 : Math.max(normalizedProgress, 95);
    Animated.timing(animatedProgress, {
      duration: normalizedProgress >= 100 ? 220 : 5_000,
      easing: Easing.bezier(0.2, 0.8, 0.2, 1),
      toValue: target,
      useNativeDriver: false
    }).start();
  }, [animatedProgress, normalizedProgress, reduceMotion]);

  const mapClipWidth = animatedProgress.interpolate({ inputRange: [0, 100], outputRange: ["32%", "92%"], extrapolate: "clamp" });
  return (
    <View style={styles.page}>
      <PlanningBackground />
      <View style={styles.header}>
        <Text style={styles.brand}>路明</Text>
        {onCancel ? (
          <Pressable accessibilityRole="button" accessibilityLabel="取消当前规划" accessibilityState={{ disabled: cancelBusy }} disabled={cancelBusy} hitSlop={ui.hitSlop} onPress={onCancel} style={({ pressed }) => [styles.cancel, pressed && styles.pressed, cancelBusy && styles.disabled]}>
            <Text style={styles.cancelText}>{cancelBusy ? "取消中" : "取消规划"}</Text>
          </Pressable>
        ) : null}
      </View>
      <View style={styles.main}>
        <Text accessibilityRole="header" style={styles.title}>{candidateCount > 0 ? `正在核对 ${candidateCount} 个候选方案` : "正在为你规划路线"}</Text>
        <Text style={styles.description}>{originText || "起点"} → {destinationText || "终点"}</Text>
        <View accessible accessibilityLabel="规划数据正在汇聚的世界地图" onLayout={(event) => setMapWidth(Math.round(event.nativeEvent.layout.width))} style={styles.mapFrame}>
          <Image source={worldMapImage} resizeMode="contain" style={[styles.mapImage, styles.mapBase]} />
          <Animated.View pointerEvents="none" style={[styles.flowClip, { width: mapClipWidth }] }>
            <Image source={worldMapFlowImage} resizeMode="contain" style={[styles.flowImage, mapWidth ? { width: mapWidth } : null]} />
          </Animated.View>
          <Animated.View pointerEvents="none" style={[styles.glowSweep, { left: mapClipWidth }]}>
            <MapSweep />
          </Animated.View>
        </View>
        <View style={styles.progressCopy}>
          <Text style={styles.progressTask}>{stagePresentation.currentTask}</Text>
          <Text style={styles.progressValue}>{normalizedProgress}%</Text>
        </View>
        <View accessibilityLabel={`规划进度${normalizedProgress}%`} accessibilityRole="progressbar" style={styles.progressTrack}>
          <View style={[styles.progressFill, { width: `${normalizedProgress}%` }]} />
        </View>
        <PlanningStageList progress={normalizedProgress} />
        <Text style={styles.note}>可以离开此页面，规划完成后会保留结果。</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, minHeight: 700, overflow: "hidden", paddingBottom: ui.spacing.xl, paddingHorizontal: 18, paddingTop: 10, position: "relative" },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  brand: { color: ui.colors.primaryDeep, fontSize: 15, fontWeight: "800" },
  cancel: { alignItems: "center", backgroundColor: "rgba(255,255,255,0.72)", borderRadius: 11, justifyContent: "center", minHeight: 40, paddingHorizontal: ui.spacing.md },
  cancelText: { color: ui.colors.planningCancelText, fontSize: 12, fontWeight: "700" },
  pressed: { opacity: 0.72, transform: [{ scale: 0.98 }] },
  main: { flex: 1, justifyContent: "center" },
  title: { color: ui.colors.text, fontSize: 30, fontWeight: "800", letterSpacing: -0.75, lineHeight: 36, maxWidth: 340 },
  description: { color: ui.colors.textSecondary, fontSize: 13, lineHeight: 20.8, marginTop: 10 },
  mapFrame: { backgroundColor: ui.colors.planningMap, borderRadius: ui.radius.card, height: 204, marginTop: ui.spacing.xl, overflow: "hidden", position: "relative" },
  mapImage: { height: "100%", left: 0, position: "absolute", top: 0, width: "100%" },
  mapBase: { opacity: 0.94 },
  flowClip: { bottom: 0, left: 0, overflow: "hidden", position: "absolute", top: 0 },
  flowImage: { height: "100%", left: 0, position: "absolute", top: 0, width: "100%" },
  glowSweep: { bottom: 0, marginLeft: -21, position: "absolute", top: 0, width: 42 },
  progressCopy: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", marginBottom: ui.spacing.sm, marginTop: 14 },
  progressTask: { color: ui.colors.text, flex: 1, fontSize: 14, fontWeight: "800", lineHeight: 20 },
  progressValue: { color: ui.colors.primaryDeep, fontSize: 13, fontWeight: "800", marginLeft: ui.spacing.md },
  progressTrack: { backgroundColor: ui.colors.disabled, borderRadius: ui.radius.pill, height: 4, overflow: "hidden" },
  progressFill: { backgroundColor: ui.colors.primary, borderRadius: ui.radius.pill, height: "100%" },
  note: { color: ui.colors.textSecondary, fontSize: 10, lineHeight: 16, marginTop: ui.spacing.md, textAlign: "center" },
  disabled: { backgroundColor: ui.colors.disabled }
});
