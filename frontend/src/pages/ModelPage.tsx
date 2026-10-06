import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDate, formatNumber, formatPercent } from "../format";
import { MODEL_KIND_LABELS } from "../labels";
import { useSession } from "../session";
import type { Aggregate, DriftReport, ExperimentSummary, ModelEvent, ModelInfo } from "../types";

const pm = (a: Aggregate) => (a.std > 0 ? `${formatNumber(a.mean, 3)} ± ${formatNumber(a.std, 3)}` : formatNumber(a.mean, 3));
const LEVEL_LABELS = { ok: "в норме", warning: "есть изменения", alert: "значительные изменения" } as const;
const EVENT_LABELS: Record<string, string> = {
  retrained: "Модель переобучена и обновлена",
  retrain_rejected: "Новая модель отклонена проверкой качества",
  retrain_skipped: "Переобучение не потребовалось",
  retrain_failed: "Ошибка переобучения",
};

/** Понятные названия наборов результатов экспериментов (каталоги backend/experiments/*). */
const RUN_TITLES: Record<string, string> = {
  results: "Синтетические данные",
  results_ibm: "IBM, 5% клиентов",
  results_ibm_full: "IBM, полный объём: базовые признаки",
  results_ibm_full_pop: "IBM, полный объём: с популяционными признаками",
  results_ibm_full_notime: "IBM, полный объём: итоговая конфигурация",
  results_ibm_final: "IBM, финальная проверка (2003–2009)",
};
const runTitle = (name: string) => {
  if (RUN_TITLES[name]) return RUN_TITLES[name];
  const prelim = name.match(/^results_ibm(\d+)$/);
  return prelim ? `IBM, предварительный прогон ${prelim[1]}` : name;
};

function Experiments({ summary }: { summary: ExperimentSummary }) {
  const budgets = Object.keys(Object.values(summary.models)[0]?.budget ?? {});
  return (
    <>
      <div className="card">
        <h3>Сравнение методов на тестовой части</h3>
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
                <th className="num">AP</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.models).map(([name, r]) => (
                <tr key={name}>
                  <td className="nowrap">{name}</td>
                  <td className="muted-cell">{r.supervised ? "с учителем" : "без учителя"}</td>
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
        <p className="hint">
          Порог выбран по максимуму F1 на валидационной части. AP (Average Precision) — средняя точность по всем порогам; при редких аномалиях
          её сравнивают с долей аномалий, а не с единицей.
          {summary.seeds.length > 1 && ` Значения — среднее ± отклонение по ${summary.seeds.length} наборам.`}
        </p>
      </div>
      {budgets.length > 0 && (
        <div className="card">
          <h3>Если проверять только часть операций с наибольшей оценкой</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Метод</th>
                  {budgets.map((b) => (
                    <th key={b} className="num">
                      Проверено {formatPercent(Number(b), 1)}: точность / найдено
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.models).map(([name, r]) => (
                  <tr key={name}>
                    <td className="nowrap">{name}</td>
                    {budgets.map((b) => (
                      <td key={b} className="num">
                        {r.budget ? `${formatPercent(r.budget[b].precision.mean, 1)} / ${formatPercent(r.budget[b].recall.mean, 1)}` : "—"}
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
                  <th className="num">AP</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.ablation).map(([name, r]) => (
                  <tr key={name}>
                    <td className="nowrap">{name}</td>
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
  if (!drift.available) return <p className="muted">{drift.reason}</p>;
  return (
    <>
      <p className="lead">
        Состояние: <strong className={`level-${drift.status}`}>{LEVEL_LABELS[drift.status!]}</strong>
      </p>
      <p className="muted">
        Проверено последних операций: {formatNumber(drift.window!, 0)}. Доля отмеченных операций {formatPercent(drift.flagged_share!)} (при обучении{" "}
        {formatPercent(drift.expected_flagged_share!)}).
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Признак</th>
              <th className="num">Индекс PSI</th>
              <th>Оценка</th>
            </tr>
          </thead>
          <tbody>
            {drift.features!.slice(0, 8).map((f) => (
              <tr key={f.feature}>
                <td>{f.label ?? f.feature}</td>
                <td className="num">{formatNumber(f.psi, 3)}</td>
                <td className={`level-${f.level}`}>{LEVEL_LABELS[f.level]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">
        PSI показывает, насколько распределение признака в последних операциях отличается от обучающих данных: до {drift.thresholds!.warning} — стабильно,
        выше {drift.thresholds!.alert} — существенный сдвиг. При существенном сдвиге модель переобучается автоматически.
      </p>
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
      setMessage("Переобучение запущено. Результат появится в журнале модели через несколько минут.");
      window.setTimeout(load, 5000);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (error) return <div className="alert-error">Не удалось загрузить сведения о модели: {error}</div>;
  if (!info) return <div className="card loading">Загрузка…</div>;
  const m = info.model;
  const runs = info.experiment_runs ?? [];
  const summary = runs[run]?.summary ?? info.experiments;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Модель</h1>
          <p className="muted">Рабочая модель, контроль изменений в данных и результаты экспериментов.</p>
        </div>
        {me.role === "admin" && (
          <button type="button" className="btn primary" onClick={retrain}>
            Переобучить на накопленных данных
          </button>
        )}
      </div>
      {message && <div className="alert-success">{message}</div>}

      <div className="grid-2">
        <div className="card">
          <h3>Рабочая модель</h3>
          <dl className="props">
            <dt>Метод</dt>
            <dd>{MODEL_KIND_LABELS[m.kind] ?? m.kind}</dd>
            <dt>Обучена</dt>
            <dd>{formatDate(m.trained_at)}</dd>
            <dt>Пороги риска</dt>
            <dd>
              средний — от {formatNumber(m.thresholds.medium, 2)}, высокий — от {formatNumber(m.thresholds.high, 2)}
            </dd>
            <dt>Признаков</dt>
            <dd>{m.feature_names.length}</dd>
            {m.metrics.test && (
              <>
                <dt>Качество на тесте</dt>
                <dd>
                  найдено {formatPercent(m.metrics.test.recall, 0)} аномалий, верных срабатываний {formatPercent(m.metrics.test.precision, 0)}
                </dd>
              </>
            )}
            <dt>Версия</dt>
            <dd className="mono muted">{m.version}</dd>
          </dl>
        </div>
        <div className="card">
          <h3>Журнал модели</h3>
          {events.length === 0 ? (
            <p className="muted">Событий пока нет.</p>
          ) : (
            <ul className="timeline">
              {events.map((e) => (
                <li key={e.id}>
                  <span className="muted">{formatDate(e.created_at)}</span>
                  <span>{EVENT_LABELS[e.event_type] ?? e.event_type}</span>
                  {typeof e.details.reason === "string" && <span className="muted">{e.details.reason}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Изменения в данных (дрейф)</h3>
        <DriftPanel drift={drift} />
      </div>

      <div className="section-head">
        <h2>Результаты экспериментов</h2>
        {runs.length > 1 && (
          <select value={run} onChange={(e) => setRun(Number(e.target.value))} aria-label="Набор результатов">
            {runs.map((r, i) => (
              <option key={r.name} value={i}>
                {runTitle(r.name)}
                {r.rows ? ` — ${formatNumber(r.rows, 0)} операций` : ""}
              </option>
            ))}
          </select>
        )}
      </div>
      {summary ? (
        <Experiments summary={summary} />
      ) : (
        <div className="card muted">Результаты экспериментов не найдены. Запустите: python -m app.ml.experiments</div>
      )}
    </div>
  );
}
