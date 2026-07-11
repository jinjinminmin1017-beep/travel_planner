import { Pressable, StyleSheet, Text, View } from "react-native";
import { ui } from "../../designSystem";

type Props = { favorite: boolean; disabled?: boolean; onFavorite: () => void; onDetails: () => void };

export function ResultsBottomAction({ favorite, disabled, onFavorite, onDetails }: Props) {
  return (
    <View style={styles.bar}>
      <View style={styles.content}>
        <Pressable accessibilityRole="button" accessibilityLabel={favorite ? "取消收藏当前方案" : "收藏当前方案"} accessibilityState={{ disabled }} disabled={disabled} onPress={onFavorite} style={({ pressed }) => [styles.favorite, pressed && styles.pressed, disabled && styles.disabled]}>
          <Text style={styles.favoriteText}>{favorite ? "已收藏" : "收藏"}</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="查看完整路线" accessibilityState={{ disabled }} disabled={disabled} onPress={onDetails} style={({ pressed }) => [styles.primary, pressed && styles.pressed, disabled && styles.disabled]}>
          <Text style={styles.primaryText}>查看完整路线</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { backgroundColor: ui.colors.surface, borderTopColor: ui.colors.line, borderTopWidth: StyleSheet.hairlineWidth, paddingHorizontal: ui.spacing.lg, paddingVertical: ui.spacing.sm },
  content: { alignSelf: "center", flexDirection: "row", gap: ui.spacing.sm, maxWidth: ui.contentMaxWidth, width: "100%" },
  favorite: { alignItems: "center", backgroundColor: ui.colors.primarySoft, borderRadius: ui.radius.control, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.lg },
  favoriteText: { color: ui.colors.primaryDeep, fontSize: 14, fontWeight: "800" },
  primary: { alignItems: "center", backgroundColor: ui.colors.primary, borderRadius: ui.radius.control, flex: 1, justifyContent: "center", minHeight: ui.touchTarget, paddingHorizontal: ui.spacing.lg },
  primaryText: { color: ui.colors.surface, fontSize: 14, fontWeight: "800" },
  pressed: { opacity: 0.8, transform: [{ scale: 0.98 }] },
  disabled: { backgroundColor: ui.colors.disabled }
});
