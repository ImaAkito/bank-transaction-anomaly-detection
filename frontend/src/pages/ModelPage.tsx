import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate, formatNumber, formatPercent } from "../format";
import { useSession } from "../session";
import type { Aggregate, DriftReport, ExperimentSummary, ModelEvent, ModelInfo } from "../types";

const pm = (a: Aggregate) => `${formatNumber(a.mean, 3)} ± ${formatNumber(a.std, 3)}`;
const LEVEL_LABELS = { ok: "в норме", warning: "предупреждение", alert: "значительный дрейф" } as const;
const EVENT_LABELS: Record<string, string> = {
  retrained: "Переобучение: новая модель развёрнута",
  retrain_rejected: "Переобучение: кандидат отклонён проверкой",
  retrain_skipped: "Переобучение пропущено",
  retrain_failed: "Переобучение: ошибка",
};

function Experiments({ summary }: { summary: ExperimentSummary }) {
  const budgets = Object.keys(Object.values(summary.models)[0]?.budget ?? {});
  return (
    <>
      <div className="card">
        <h3>Сравнение методов (тестовая выборка, среднее ± σ по {summary.seeds.length} наборам)</h3>
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
                <th className="num">AP (PR-AUC)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.models).map(([name, r]) => (
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
      {budgets.length > 0 && (
        <div className="card">
          <h3>Фиксированный бюджет оповещений (Precision / Recall)</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Метод</th>
                  {budgets.map((b) => (
                    <th key={b} className="num">
                      Топ {formatPercent(Number(b), 1)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.models).map(([name, r]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    {budgets.map((b) => (
                      <td key={b} className="num">
                        {r.budget ? `${formatNumber(r.budget[b].precision.mean, 3)} / ${formatNumber(r.budget[b].recall.mean, 3)}` : "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {Object.keys(summary.ablation).length > 0 && (
      <div className="card">
        <h3>Влияние групп признаков (Isolation Forest)</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Набор признаков</th>
                <th className="num">Признаков</th>
                <th className="num">ROC-AUC</th>
                <th className="num">AP (PR-AUC)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.ablation).map(([name, r]) => (
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
      )}
    </>
  );
}

function DriftPanel({ drift }: { drift: DriftReport | null }) {
  if (!drift) return <div className="muted">Загрузка…</div>;
  if (!drift.available) return <div className="muted">{drift.reason}</div>;
  return (
    <>
      <p>
        Состояние: <strong className={`level-${drift.status}`}>{LEVEL_LABELS[drift.status!]}</strong> · окно {drift.window} операций ·
        максимальный PSI {formatNumber(drift.max_psi!, 3)} · доля оповещений {formatPercent(drift.flagged_share!)} (при обучении{" "}
        {formatPercent(drift.expected_flagged_share!)})
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Признак</th>
              <th className="num">PSI</th>
              <th>Уровень</th>
            </tr>
          </thead>
          <tbody>
            {drift.features!.slice(0, 10).map((f) => (
              <tr key={f.feature}>
                <td className="mono">{f.feature}</td>
                <td className="num">{formatNumber(f.psi, 3)}</td>
                <td className={`level-${f.level}`}>{LEVEL_LABELS[f.level]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="muted">
        PSI ниже {drift.thresholds!.warning} — распределение стабильно, выше {drift.thresholds!.alert} — значительный сдвиг; при значительном дрейфе
        сервис переобучения обновляет модель автоматически.
      </div>
    </>
  );
}

export function ModelPage() {
  const me = useSession();
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [drift, setDrift] = useState<DriftReport | null>(null);
  const [events, setEvents] = useState<ModelEvent[]>([]);
  const [run, setRun] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.model().then(setInfo).catch((e: Error) => setError(e.message));
    api.drift().then(setDrift).catch(() => setDrift({ available: false, reason: "Не удалось рассчитать дрейф" }));
    api.modelEvents().then(setEvents).catch(() => setEvents([]));
  };
  useEffect(load, []);

  const retrain = async () => {
    try {
      await api.retrain();
      setMessage("Переобучение запущено; результат появится в журнале модели.");
      window.setTimeout(load, 5000);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (error) return <div className="alert-error">Ошибка: {error}</div>;
  if (!info) return <div className="card">Загрузка…</div>;
  const m = info.model;
  const runs = info.experiment_runs ?? [];
  const summary = runs[run]?.summary ?? info.experiments;

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2>Рабочая модель</h2>
          {me.role === "admin" && (
            <button type="button" className="btn" onClick={retrain}>
              Переобучить на накопленных данных
            </button>
          )}
        </div>
        {message && <div className="note">{message}</div>}
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
                {formatNumber(m.metrics.test.f1, 2)} · ROC-AUC {formatNumber(m.metrics.test.roc_auc, 3)} · AP{" "}
                {formatNumber(m.metrics.test.pr_auc, 3)}
              </dd>
            </>
          )}
        </dl>
      </div>

      <div className="card">
        <h3>Мониторинг дрейфа данных</h3>
        <DriftPanel drift={drift} />
      </div>

      <div className="card">
        <h3>Журнал модели</h3>
        {events.length === 0 ? (
          <div className="muted">Событий нет</div>
        ) : (
          <ul className="reasons">
            {events.map((e) => (
              <li key={e.id}>
                {formatDate(e.created_at)} — {EVENT_LABELS[e.event_type] ?? e.event_type}
                {e.model_version && <span className="mono"> · {e.model_version}</span>}
                {typeof e.details.reason === "string" && <span className="muted"> · {e.details.reason}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {runs.length > 1 && (
        <div className="card run-select">
          <span>Результаты экспериментов:</span>
          <select value={run} onChange={(e) => setRun(Number(e.target.value))}>
            {runs.map((r, i) => (
              <option key={r.name} value={i}>
                {r.name}
                {r.rows ? ` — ${formatNumber(r.rows, 0)} операций` : ""}
                {r.anomaly_share ? `, аномалий ${formatPercent(r.anomaly_share, 2)}` : ""}
              </option>
            ))}
          </select>
        </div>
      )}
      {summary ? <Experiments summary={summary} /> : <div className="card muted">Результаты экспериментов не найдены. Запустите: python -m app.ml.experiments</div>}
    </div>
  );
}
