import { RISK_COLORS, formatDate, formatMoney } from "../format";
import { link } from "../router";
import type { Transaction } from "../types";

/** Точечный график активности клиента: время по X, сумма (логарифмическая шкала) по Y, цвет — уровень риска. */
export function ActivityChart({ items, highlightId }: { items: Transaction[]; highlightId?: string }) {
  if (items.length === 0) return <div className="empty">Нет данных</div>;
  const width = 860;
  const height = 240;
  const pad = { left: 56, right: 16, top: 12, bottom: 28 };
  const times = items.map((t) => new Date(t.timestamp).getTime());
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const values = items.map((t) => Math.log10(Math.max(t.amount_base, 1)));
  const minV = Math.floor(Math.min(...values));
  const maxV = Math.ceil(Math.max(...values));
  const x = (t: number) => pad.left + ((t - minT) / Math.max(maxT - minT, 1)) * (width - pad.left - pad.right);
  const y = (v: number) => pad.top + (1 - (v - minV) / Math.max(maxV - minV, 1)) * (height - pad.top - pad.bottom);
  const ticks: number[] = [];
  for (let v = minV; v <= maxV; v += 1) ticks.push(v);

  const ordered = [...items].sort((a, b) => (a.analysis.risk_level === "low" ? -1 : 1) - (b.analysis.risk_level === "low" ? -1 : 1));
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart" role="img" aria-label="График активности клиента">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={pad.left} x2={width - pad.right} y1={y(v)} y2={y(v)} className="grid" />
          <text x={pad.left - 8} y={y(v) + 4} textAnchor="end" className="axis">
            {new Intl.NumberFormat("ru-RU", { notation: "compact" }).format(10 ** v)}
          </text>
        </g>
      ))}
      <text x={pad.left} y={height - 6} className="axis">
        {new Date(minT).toLocaleDateString("ru-RU")}
      </text>
      <text x={width - pad.right} y={height - 6} textAnchor="end" className="axis">
        {new Date(maxT).toLocaleDateString("ru-RU")}
      </text>
      {ordered.map((t) => {
        const current = t.transaction_id === highlightId;
        const level = t.analysis.risk_level;
        return (
          <a key={t.transaction_id} href={link("transactions", t.transaction_id)}>
            <circle
              cx={x(new Date(t.timestamp).getTime())}
              cy={y(Math.log10(Math.max(t.amount_base, 1)))}
              r={current ? 7 : level === "low" ? 3 : 5}
              fill={RISK_COLORS[level]}
              fillOpacity={level === "low" ? 0.55 : 0.95}
              stroke={current ? "var(--text)" : "none"}
              strokeWidth={2}
            >
              <title>{`${formatDate(t.timestamp)}\n${formatMoney(t.amount, t.currency)} · ${t.category}\nоценка ${t.analysis.anomaly_score.toFixed(2)}`}</title>
            </circle>
          </a>
        );
      })}
    </svg>
  );
}

export function HourHistogram({ counts, typical }: { counts: number[]; typical: number[] }) {
  const max = Math.max(...counts, 1);
  return (
    <div>
      <div className="hours">
        {counts.map((c, h) => (
          <div key={h} className="hour-col" title={`${String(h).padStart(2, "0")}:00 — ${c} оп.`}>
            <div className={`hour-bar ${typical.includes(h) ? "typical" : ""}`} style={{ height: `${(c / max) * 100}%` }} />
            <span>{h % 3 === 0 ? h : ""}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BarList({ data, limit = 8 }: { data: Record<string, number>; limit?: number }) {
  const entries = Object.entries(data).slice(0, limit);
  const total = Object.values(data).reduce((a, b) => a + b, 0) || 1;
  if (entries.length === 0) return <div className="muted">нет данных</div>;
  return (
    <div className="barlist">
      {entries.map(([name, value]) => (
        <div key={name} className="barlist-row">
          <span className="barlist-name">{name}</span>
          <div className="barlist-track">
            <div className="barlist-fill" style={{ width: `${(value / total) * 100}%` }} />
          </div>
          <span className="barlist-value">{value}</span>
        </div>
      ))}
    </div>
  );
}
