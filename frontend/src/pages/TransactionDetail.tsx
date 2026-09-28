import { useEffect, useState } from "react";
import { api } from "../api";
import { RiskBadge, ScoreBar, StatusBadge } from "../components/Badges";
import { ActivityChart } from "../components/Charts";
import { FactorBars } from "../components/FactorBars";
import { TransactionTable } from "../components/TransactionTable";
import { formatDate, formatMoney, formatNumber, TYPE_LABELS } from "../format";
import { link } from "../router";
import type { ClientDetail, Transaction } from "../types";
import { useLiveFeed } from "../useLiveFeed";

export function TransactionDetail({ id }: { id: string }) {
  const [tx, setTx] = useState<Transaction | null>(null);
  const [client, setClient] = useState<ClientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState(() => localStorage.getItem("reviewer") ?? "analyst");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTx(null);
    setClient(null);
    api
      .transaction(id)
      .then((t) => {
        setTx(t);
        return api.client(t.client_id);
      })
      .then(setClient)
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useLiveFeed((event) => {
    if (event.data.transaction_id === id) setTx(event.data);
  });

  const review = async (status: string) => {
    setBusy(true);
    try {
      localStorage.setItem("reviewer", reviewer);
      const updated = await api.review(id, status, reviewer, comment);
      setTx(updated);
      setComment("");
      setClient(await api.client(updated.client_id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error && !tx) return <div className="alert-error">Ошибка: {error}</div>;
  if (!tx) return <div className="card">Загрузка…</div>;
  const a = tx.analysis;

  return (
    <div className="stack">
      {error && <div className="alert-error">Ошибка: {error}</div>}
      <div className="card">
        <div className="detail-head">
          <div>
            <div className="muted">
              <a href="#/transactions">← К списку</a>
            </div>
            <h2 className="mono">{tx.transaction_id}</h2>
            <div className="muted">
              Клиент <a href={link("clients", tx.client_id)}>{tx.client_id}</a> · {formatDate(tx.timestamp)}
            </div>
          </div>
          <div className="verdict">
            <div className="verdict-row">
              <span>Уровень риска:</span> <RiskBadge level={a.risk_level} />
            </div>
            <div className="verdict-row">
              <span>Оценка аномальности:</span> <strong className="big">{formatNumber(a.anomaly_score, 2)}</strong>
            </div>
            <ScoreBar score={a.anomaly_score} level={a.risk_level} />
            <StatusBadge status={a.status} />
          </div>
        </div>
        <p className="disclaimer">
          Оценка является аналитической: она показывает отличие операции от типичного поведения клиента и не означает, что операция мошенническая. Решение принимает специалист.
        </p>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Почему сработала система</h3>
          <p className="summary">{a.summary}</p>
          {a.deviation_types.length > 0 && (
            <div className="chips static">
              {a.deviation_types.map((t) => (
                <span key={t} className="chip on">
                  {TYPE_LABELS[t] ?? t}
                </span>
              ))}
            </div>
          )}
          {a.reasons.length > 0 ? (
            <ul className="reasons">
              {a.reasons.map((r) => (
                <li key={r.code} className={r.severity >= 0.7 ? "strong" : ""}>
                  {r.text}
                </li>
              ))}
            </ul>
          ) : (
            <div className="muted">Отдельных факторов отклонения не выявлено</div>
          )}
          {!a.profile_updated && (
            <div className="note">Операция удержана вне профиля клиента до решения специалиста: она не искажает типичное поведение.</div>
          )}
        </div>

        <div className="card">
          <h3>Параметры операции</h3>
          <dl className="props">
            <dt>Сумма</dt>
            <dd>
              {formatMoney(tx.amount, tx.currency)}
              {tx.currency !== "RUB" && <span className="muted"> (≈ {formatMoney(tx.amount_base, "RUB")})</span>}
            </dd>
            <dt>Категория</dt>
            <dd>{tx.category}</dd>
            <dt>Канал</dt>
            <dd>{tx.channel}</dd>
            <dt>Получатель</dt>
            <dd>
              {tx.recipient_id ?? "—"}
              {tx.recipient_category && <span className="muted"> ({tx.recipient_category})</span>}
            </dd>
            <dt>Получена системой</dt>
            <dd>{formatDate(tx.received_at)}</dd>
            <dt>Модель</dt>
            <dd>
              {a.model_kind} <span className="muted">· {a.model_version} · {formatNumber(a.latency_ms, 1)} мс</span>
            </dd>
            {tx.simulation_label !== null && (
              <>
                <dt>Метка симулятора</dt>
                <dd>{tx.simulation_label ? `аномалия (${tx.simulation_anomaly_type ?? "—"})` : "нормальная операция"}</dd>
              </>
            )}
          </dl>
        </div>
      </div>

      <div className="card">
        <h3>Факторы, повлиявшие на оценку (SHAP)</h3>
        <FactorBars factors={a.factors} />
      </div>

      <div className="card">
        <h3>Решение специалиста</h3>
        {a.reviewed_at && (
          <div className="note">
            Последнее решение: {a.reviewed_by ?? "—"}, {formatDate(a.reviewed_at)}
            {a.review_comment && <> — «{a.review_comment}»</>}
          </div>
        )}
        <div className="review-form">
          <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Ваше имя" aria-label="Ваше имя" />
          <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Комментарий (необязательно)" aria-label="Комментарий" className="grow" />
          <button type="button" className="btn ok" disabled={busy} onClick={() => review("reviewed_normal")}>
            Операция нормальная
          </button>
          <button type="button" className="btn danger" disabled={busy} onClick={() => review("reviewed_suspicious")}>
            Подозрительная
          </button>
          <button type="button" className="btn" disabled={busy || a.status === "needs_review"} onClick={() => review("needs_review")}>
            Вернуть на проверку
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Активность клиента</h3>
        {client ? (
          <>
            <ActivityChart items={client.recent} highlightId={tx.transaction_id} />
            <div className="muted">
              Медианная сумма клиента: {client.profile.median_amount ? formatMoney(client.profile.median_amount, "RUB") : "—"}
              {" · "}типичные часы: {client.profile.typical_hours.length ? client.profile.typical_hours.map((h) => `${h}:00`).join(", ") : "—"}
              {" · "}категории: {Object.keys(client.profile.categories).slice(0, 5).join(", ") || "—"}
            </div>
            <TransactionTable items={client.recent.slice(0, 15)} showClient={false} highlightId={tx.transaction_id} />
          </>
        ) : (
          <div className="muted">Загрузка истории…</div>
        )}
      </div>
    </div>
  );
}
