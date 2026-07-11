import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, Image, Pressable, StyleSheet, Text, View } from "react-native";
import worldMapFlowImage from "../../../assets/maps/world-map-flow.png";
import worldMapImage from "../../../assets/maps/world-map.png";
import { ui } from "../../designSystem";
import { PlanningStageList } from "./PlanningStageList";

type Props = {
  progress: number;
  originText?: string;
  destinationText?: string;
  statusText?: string;
  onCancel?: () => void;
};

export function PlanningProgressScreen({ progress, originText, destinationText, statusText, onCancel }: Props) {
  const normalizedProgress = Math.max(0, Math.min(100, Math.round(progress)));
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
      duration: normalizedProgress >= 100 ? 220 : 18_000,
      toValue: target,
      useNativeDriver: false
    }).start();
  }, [animatedProgress, normalizedProgress, reduceMotion]);

  const mapClipWidth = animatedProgress.interpolate({ inputRange: [0, 100], outputRange: ["0%", "100%"], extrapolate: "clamp" });
  const routeDescription = originText && destinationText ? `已理解${originText}到${destinationText}的行程需求` : "正在理解你的行程需求";

  return (
    <View style={styles.page}>
      <View style={styles.header}>
        <Text style={styles.brand}>路明</Text>
        {onCancel ? (
          <Pressable accessibilityRole="button" accessibilityLabel="取消当前规划" hitSlop={ui.hitSlop} onPress={onCancel} style={({ pressed }) => [styles.cancel, pressed && styles.pressed]}>
            <Text style={styles.cancelText}>取消规划</Text>
          </Pressable>
        ) : null}
      </View>
      <Text accessibilityRole="header" style={styles.title}>正在为你拼出更稳妥的路线</Text>
      <Text style={styles.description}>{routeDescription}</Text>
      <View accessible accessibilityLabel="规划数据正在汇聚的世界地图" onLayout={(event) => setMapWidth(Math.round(event.nativeEvent.layout.width))} style={styles.mapFrame}>
        <Image source={worldMapImage} resizeMode="contain" style={styles.mapImage} />
        <Animated.View pointerEvents="none" style={[styles.flowClip, { width: mapClipWidth }]}>
          <Image source={worldMapFlowImage} resizeMode="contain" style={[styles.flowImage, mapWidth ? { width: mapWidth } : null]} />
        </Animated.View>
      </View>
      <PlanningStageList progress={normalizedProgress} />
      <View style={styles.progressHeader}>
        <Text style={styles.progressText}>{statusText || "正在汇总可用路线与数据来源"}</Text>
        <Text accessibilityLabel={`当前实际进度百分之${normalizedProgress}`} style={styles.progressValue}>{normalizedProgress}%</Text>
      </View>
      <View style={styles.track}><View style={[styles.fill, { width: `${normalizedProgress}%` }]} /></View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: ui.spacing.lg, paddingBottom: ui.spacing.xl },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  brand: { color: ui.colors.primaryDeep, fontSize: 20, fontWeight: "800" },
  cancel: { alignItems: "center", justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.md },
  cancelText: { color: ui.colors.primary, fontSize: 14, fontWeight: "700" },
  pressed: { opacity: 0.72, transform: [{ scale: 0.98 }] },
  title: { color: ui.colors.text, fontSize: 30, fontWeight: "800", lineHeight: 36, maxWidth: 460 },
  description: { color: ui.colors.textSecondary, fontSize: 14, lineHeight: 20, marginTop: -ui.spacing.sm },
  mapFrame: { aspectRatio: 1.55, backgroundColor: ui.colors.primaryDeep, borderRadius: ui.radius.card, minHeight: 220, overflow: "hidden", position: "relative" },
  mapImage: { height: "100%", left: 0, position: "absolute", top: 0, width: "100%" },
  flowClip: { bottom: 0, left: 0, overflow: "hidden", position: "absolute", top: 0 },
  flowImage: { height: "100%", left: 0, position: "absolute", top: 0, width: "100%" },
  progressHeader: { alignItems: "flex-end", flexDirection: "row", justifyContent: "space-between" },
  progressText: { color: ui.colors.textSecondary, flex: 1, fontSize: 12, lineHeight: 18, paddingRight: ui.spacing.md },
  progressValue: { color: ui.colors.primaryDeep, fontSize: 14, fontWeight: "800" },
  track: { backgroundColor: ui.colors.disabled, borderRadius: ui.radius.pill, height: 6, overflow: "hidden", marginTop: -ui.spacing.sm },
  fill: { backgroundColor: ui.colors.primary, borderRadius: ui.radius.pill, height: "100%" }
});
