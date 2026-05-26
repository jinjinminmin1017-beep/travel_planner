import type { Money } from "../types";

export function formatMoney(money: Money) {
  return money.display_text;
}

export function minutesToText(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours ? `${hours}小时${rest}分` : `${rest}分`;
}

export function slotLabel(type: string) {
  if (type === "CHEAPEST") return "最优惠";
  if (type === "MOST_COMFORTABLE") return "最舒适";
  return "综合推荐";
}

export function riskLabel(level: string) {
  if (level === "LOW") return "低风险";
  if (level === "MEDIUM") return "中风险";
  if (level === "HIGH") return "高风险";
  return "已阻断";
}
