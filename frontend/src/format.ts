import type { RiskLevel, Status } from "./types";

/** Базовая валюта системы — белорусский рубль. */
export const BASE_CURRENCY = "BYN";

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

const moneyFormat = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Сумма с обозначением валюты; белорусский рубль — официальным знаком «Br». */
export function formatMoney(amount: number, currency: string = BASE_CURRENCY): string {
  if (currency === "BYN") return `${moneyFormat.format(amount)} Br`;
  try {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency, currencyDisplay: "narrowSymbol" }).format(amount);
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
  return new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDay(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

/** Часы активности в виде интервалов: [9,10,11,12,20,21] → «9:00–13:00, 20:00–22:00»; [0,1,22,23] → «22:00–2:00». */
export function formatHourRanges(hours: number[]): string {
  if (hours.length === 0) return "—";
  if (hours.length === 24) return "круглосуточно";
  const sorted = [...hours].sort((a, b) => a - b);
  const ranges: [number, number][] = [];
  for (const h of sorted) {
    const last = ranges[ranges.length - 1];
    if (last && h === last[1] + 1) last[1] = h;
    else ranges.push([h, h]);
  }
  // Интервал через полночь (например, 17:00–0:00 и 0:00–3:00) объединяется в один: 17:00–3:00.
  if (ranges.length > 1 && ranges[0][0] === 0 && ranges[ranges.length - 1][1] === 23) {
    const first = ranges.shift()!;
    ranges[ranges.length - 1][1] = first[1];
  }
  return ranges.map(([from, to]) => `${from}:00–${(to + 1) % 24}:00`).join(", ");
}

export const RISK_LABELS: Record<RiskLevel, string> = { low: "низкий", medium: "средний", high: "высокий" };

export const STATUS_LABELS: Record<Status, string> = {
  normal: "Норма",
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
  status_changed: "Решение специалиста",
};

export const RISK_COLORS: Record<RiskLevel, string> = {
  low: "var(--risk-low)",
  medium: "var(--risk-medium)",
  high: "var(--risk-high)",
};

export const ROLE_NAMES: Record<string, string> = {
  viewer: "Наблюдатель",
  analyst: "Аналитик",
  admin: "Администратор",
  service: "Сервис",
};

/** Переход по ссылке внутри приложения (hash-маршрутизация). */
export const go = (href: string) => {
  window.location.hash = href.replace(/^#/, "");
};
