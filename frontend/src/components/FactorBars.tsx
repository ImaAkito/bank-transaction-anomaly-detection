import { formatNumber } from "../format";
import type { Factor } from "../types";

/** Вклад признаков в оценку (SHAP): красные повышают степень аномальности, зелёные снижают. */
export function FactorBars({ factors }: { factors: Factor[] }) {
  if (factors.length === 0) return <div className="muted">Вклад признаков рассчитывается для операций со средним и высоким риском</div>;
  const max = Math.max(...factors.map((f) => Math.abs(f.contribution)), 1e-9);
  return (
    <div className="factors">
      {factors.map((f) => (
        <div key={f.feature} className="factor-row">
          <div className="factor-label">
            {f.label}
            <span className="muted"> · значение {formatNumber(f.value, 2)}</span>
          </div>
          <div className="factor-track">
            <div className="factor-center" />
            <div
              className={`factor-bar ${f.direction}`}
              style={{
                width: `${(Math.abs(f.contribution) / max) * 50}%`,
                [f.direction === "increases" ? "left" : "right"]: "50%",
              }}
            />
          </div>
          <div className={`factor-value ${f.direction}`}>
            {f.contribution > 0 ? "+" : ""}
            {formatNumber(f.contribution, 3)}
          </div>
        </div>
      ))}
    </div>
  );
}
