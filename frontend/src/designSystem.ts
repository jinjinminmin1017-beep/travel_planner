export const ui = {
  colors: {
    background: "#eff4f3",
    surface: "#ffffff",
    text: "#15282b",
    textSecondary: "#5d7073",
    line: "#d9e3e1",
    primary: "#126b75",
    primaryDeep: "#0b5159",
    primarySoft: "#e4f1ef",
    onPrimaryMuted: "#d5e9e6",
    connection: "#bfe4dc",
    mapGlow: "#c9fff4",
    mapGlowSoft: "rgba(126, 233, 212, 0.26)",
    mapGlowFaint: "rgba(126, 233, 212, 0.10)",
    warning: "#8a5a18",
    warningSurface: "#fff4de",
    danger: "#9b4334",
    dangerSurface: "#fff1ee",
    success: "#26705a",
    disabled: "#dce5e3",
    disabledText: "#728184",

    // Compatibility aliases for screens that have not moved to semantic tokens yet.
    muted: "#5d7073",
    teal: "#126b75",
    tealSoft: "#e4f1ef",
    warningText: "#8a5a18"
  },
  radius: {
    small: 9,
    control: 12,
    card: 16,
    pill: 999
  },
  spacing: {
    xxs: 4,
    xs: 6,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
    xxl: 32
  },
  touchTarget: 48,
  contentMaxWidth: 720,
  hitSlop: {
    top: 8,
    bottom: 8,
    left: 8,
    right: 8
  }
} as const;
