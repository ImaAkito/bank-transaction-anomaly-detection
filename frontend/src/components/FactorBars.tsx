import type { Factor } from "../types";

/**
 * Вклад признаков в оценку модели (SHAP) в упрощённом виде: только название признака и относительная сила влияния.
 * Красная полоса — признак повысил оценку аномальности, зелёная — понизил.
 */
export function FactorBars({ factors }: { factors: Factor[] }) {
  if (factors.length === 0) return <div className="muted">Вклад признаков рассчитывается для операций со средним и высоким риском.</div>;
  const max = Math.max(...factors.map((f) => Math.abs(f.contribution)), 1e-9);
  return (
    <div className="factors">
      {factors.map((f) => (
        <div key={f.feature} className="factor-row">
          <div className="factor-label">{f.label}</div>
          <div className="factor-track" title={f.direction === "increases" ? "повышает оценку" : "понижает оценку"}>
            <div className={`factor-bar ${f.direction}`} style={{ width: `${(Math.abs(f.contribution) / max) * 100}%` }} />
          </div>
          <div className={`factor-direction ${f.direction}`}>{f.direction === "increases" ? "повышает" : "понижает"}</div>
        </div>
      ))}
    </div>
  );
}
