import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate, formatNumber } from "../format";
import type { Aggregate, ModelInfo } from "../types";

const pm = (a: Aggregate) => `${formatNumber(a.mean, 3)} ± ${formatNumber(a.std, 3)}`;

export function ModelPage() {
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.model().then(setInfo).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="alert-error">Ошибка: {error}</div>;
  if (!info) return <div className="card">Загрузка…</div>;
  const m = info.model;
  const exp = info.experiments;

  return (
    <div className="stack">
      <div className="card">
        <h2>Рабочая модель</h2>
        <dl className="props">
          <dt>Тип</dt>
          <dd>{m.kind}</dd>
          <dt>Версия</dt>
          <dd className="mono">{m.version}</dd>
          <dt>Обучена</dt>
          <dd>{formatDate(m.trained_at)}</dd>
          <dt>Пороги риска</dt>
          <dd>
            средний ≥ {formatNumber(m.thresholds.medium, 2)}, высокий ≥ {formatNumber(m.thresholds.high, 2)}
          </dd>
          <dt>Признаков</dt>
          <dd>{m.feature_names.length}</dd>
          <dt>Параметры</dt>
          <dd className="mono">{JSON.stringify(m.params)}</dd>
          {m.metrics.test && (
            <>
              <dt>Качество на тесте</dt>
              <dd>
                Precision {formatNumber(m.metrics.test.precision, 2)} · Recall {formatNumber(m.metrics.test.recall, 2)} · F1{" "}
                {formatNumber(m.metrics.test.f1, 2)} · ROC-AUC {formatNumber(m.metrics.test.roc_auc, 3)} · PR-AUC{" "}
                {formatNumber(m.metrics.test.pr_auc, 3)}
              </dd>
            </>
          )}
        </dl>
      </div>

      {exp ? (
        <>
          <div className="card">
            <h3>Сравнение методов (тестовая выборка, среднее ± σ по {exp.seeds.length} наборам)</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Метод</th>
                    <th>Тип</th>
                    <th className="num">Precision</th>
                    <th className="num">Recall</th>
                    <th className="num">F1</th>
                    <th className="num">ROC-AUC</th>
                    <th className="num">PR-AUC</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(exp.models).map(([name, r]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td>{r.supervised ? "с учителем" : "без учителя"}</td>
                      <td className="num">{pm(r.val_threshold.precision)}</td>
                      <td className="num">{pm(r.val_threshold.recall)}</td>
                      <td className="num">{pm(r.val_threshold.f1)}</td>
                      <td className="num">{pm(r.roc_auc)}</td>
                      <td className="num">{pm(r.pr_auc)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="muted">Порог классификации выбран по максимуму F1 на валидационной части.</div>
          </div>
          <div className="card">
            <h3>Влияние групп признаков (Isolation Forest)</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Набор признаков</th>
                    <th className="num">Признаков</th>
                    <th className="num">ROC-AUC</th>
                    <th className="num">PR-AUC</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(exp.ablation).map(([name, r]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="num">{r.n_features}</td>
                      <td className="num">{pm(r.roc_auc)}</td>
                      <td className="num">{pm(r.pr_auc)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        <div className="card muted">Результаты экспериментов не найдены. Запустите: python -m app.ml.experiments</div>
      )}
    </div>
  );
}
