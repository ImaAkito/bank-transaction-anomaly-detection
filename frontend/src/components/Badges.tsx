import { RISK_COLORS, RISK_LABELS, STATUS_LABELS, formatScore } from "../format";
import type { RiskLevel, Status } from "../types";

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span className={`badge risk-${level}`}>
      <span className="dot" />
      {RISK_LABELS[level]}
    </span>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge status-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function ScoreBar({ score, level }: { score: number; level: RiskLevel }) {
  return (
    <div className="scorebar" title={`Оценка аномальности ${formatScore(score)}`}>
      <div className="scorebar-fill" style={{ width: `${Math.round(score * 100)}%`, background: RISK_COLORS[level] }} />
      <span className="scorebar-text">{formatScore(score)}</span>
    </div>
  );
}
