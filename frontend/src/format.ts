import type { RiskLevel, Status } from "./types";

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

export function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency }).format(amount);
  } catch {
    return `${numberFormat.format(amount)} ${currency}`;
  }
}

export const formatNumber = (value: number, digits = 2) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);

export const formatScore = (score: number) => formatNumber(score, 2);

export const formatPercent = (value: number, digits = 1) => `${formatNumber(value * 100, digits)}%`;

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "medium" });
}

export const RISK_LABELS: Record<RiskLevel, string> = { low: "низкий", medium: "средний", high: "высокий" };

export const STATUS_LABELS: Record<Status, string> = {
  normal: "Норма (авто)",
  needs_review: "Требует проверки",
  reviewed_normal: "Проверено: норма",
  reviewed_suspicious: "Проверено: подозрительная",
};

export const TYPE_LABELS: Record<string, string> = {
  amount: "сумма",
  time: "время",
  category: "категория",
  channel: "канал",
  recipient: "получатель",
  currency: "валюта",
  velocity: "частота",
};

export const EVENT_LABELS: Record<string, string> = {
  triggered: "Срабатывание",
  status_changed: "Смена статуса",
};

export const RISK_COLORS: Record<RiskLevel, string> = {
  low: "var(--risk-low)",
  medium: "var(--risk-medium)",
  high: "var(--risk-high)",
};
