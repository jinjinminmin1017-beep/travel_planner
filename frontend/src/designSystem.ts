export const ui = {
  colors: {
    background: "#f5f7f8",
    surface: "#ffffff",
    text: "#172126",
    muted: "#66747c",
    line: "#edf0f1",
    teal: "#126b75",
    tealSoft: "#e7f2f3",
    warningSurface: "#fff8e8",
    warningText: "#6f4a06",
    danger: "#9d2f21",
    dangerSurface: "#fff7f5"
  },
  radius: {
    control: 8,
    pill: 999
  },
  spacing: {
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24
  },
  touchTarget: 44,
  contentMaxWidth: 720,
  hitSlop: {
    top: 8,
    bottom: 8,
    left: 8,
    right: 8
  }
} as const;
