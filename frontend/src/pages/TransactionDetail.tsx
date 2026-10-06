import { useEffect, useState } from "react";
import { api } from "../api";
import { RiskBadge, ScoreBar, StatusBadge } from "../components/Badges";
import { ActivityChart } from "../components/Charts";
import { ClientTransactions } from "../components/ClientTransactions";
import { FactorBars } from "../components/FactorBars";
import { formatDate, formatHourRanges, formatMoney, formatNumber } from "../format";
import { categoryLabel, channelLabel, recipientLabel } from "../labels";
import { link } from "../router";
import type { ClientDetail, Transaction } from "../types";
import { canReview, useSession } from "../session";
import { useLiveFeed } from "../useLiveFeed";

const DECISIONS = {
  reviewed_normal: "Операция отмечена как нормальная",
  reviewed_suspicious: "Операция отмечена как подозрительная",
  needs_review: "Операция возвращена на проверку",
} as const;

export function TransactionDetail({ id }: { id: string }) {
  const [tx, setTx] = useState<Transaction | null>(null);
  const [client, setClient] = useState<ClientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const me = useSession();
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem("reviewer") ?? "";
    } catch {
      return "";
    }
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTx(null);
    setClient(null);
    setSaved(null);
    api
      .transaction(id)
      .then((t) => {
        setTx(t);
        return api.client(t.client_id, 300);
      })
      .then(setClient)
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useLiveFeed((event) => {
    if (event.data.transaction_id === id) setTx(event.data);
  });

  const review = async (status: keyof typeof DECISIONS) => {
    setBusy(true);
    setSaved(null);
    try {
      try {
        if (reviewer) localStorage.setItem("reviewer", reviewer);
      } catch {
        /* хранилище недоступно */
      }
      const updated = await api.review(id, status, reviewer || "специалист", comment);
      setTx(updated);
      setComment("");
      setSaved(DECISIONS[status]);
      setError(null);
      setReloadKey((k) => k + 1);
      setClient(await api.client(updated.client_id, 300));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error && !tx) return <div className="alert-error">Не удалось открыть операцию: {error}</div>;
  if (!tx) return <div className="card loading">Загрузка операции…</div>;
  const a = tx.analysis;
  const foreign = tx.currency !== "BYN";

  return (
    <div className="stack">
      <a href="#/transactions" className="back-link">
        ← Все операции
      </a>
      {error && <div className="alert-error">Ошибка: {error}</div>}

      <div className={`card hero hero-${a.risk_level}`}>
        <div className="hero-main">
          <div className="hero-kicker">
            {categoryLabel(tx.category)} · {channelLabel(tx.channel)}
          </div>
          <h1 className="hero-title">
            {formatMoney(tx.amount, tx.currency)}
            {foreign && <span className="hero-sub"> ≈ {formatMoney(tx.amount_base)}</span>}
          </h1>
          <div className="hero-meta">
            <span>{formatDate(tx.timestamp)}</span>
            <span>
              Клиент <a href={link("clients", tx.client_id)}>{tx.client_id}</a>
            </span>
            <span className="mono muted">{tx.transaction_id}</span>
          </div>
        </div>
        <div className="hero-verdict">
          <RiskBadge level={a.risk_level} large />
          <div className="verdict-score">
            <span className="muted">Оценка аномальности</span>
            <strong>{formatNumber(a.anomaly_score, 2)}</strong>
          </div>
          <ScoreBar score={a.anomaly_score} level={a.risk_level} />
          <StatusBadge status={a.status} />
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>{a.risk_level === "low" ? "Результат анализа" : "Почему операция отмечена"}</h3>
          {a.risk_level === "low" && a.reasons.length === 0 ? (
            <p className="lead">Операция соответствует обычному поведению клиента.</p>
          ) : a.reasons.length > 0 ? (
            <ul className="reasons">
              {a.reasons.map((r) => (
                <li key={r.code} className={r.severity >= 0.7 ? "strong" : ""}>
                  {r.text}
                </li>
              ))}
            </ul>
          ) : (
            <p className="lead">Отклонение выявлено моделью по совокупности признаков, без одного явного фактора.</p>
          )}
          {!a.profile_updated && <p className="hint">Операция не учтена в профиле клиента до решения специалиста.</p>}
        </div>

        <div className="card">
          <h3>Детали операции</h3>
          <dl className="props">
            <dt>Сумма</dt>
            <dd>
              {formatMoney(tx.amount, tx.currency)}
              {foreign && <span className="muted"> ≈ {formatMoney(tx.amount_base)}</span>}
            </dd>
            <dt>Категория</dt>
            <dd>{categoryLabel(tx.category)}</dd>
            <dt>Канал</dt>
            <dd>{channelLabel(tx.channel)}</dd>
            <dt>Получатель</dt>
            <dd>{tx.recipient_category ? recipientLabel(tx.recipient_category) : "—"}</dd>
            <dt>Дата и время</dt>
            <dd>{formatDate(tx.timestamp)}</dd>
            {client && (
              <>
                <dt>Обычное время клиента</dt>
                <dd>{formatHourRanges(client.profile.typical_hours)}</dd>
              </>
            )}
          </dl>
        </div>
      </div>

      <div className="card">
        <h3>Решение специалиста</h3>
        {a.reviewed_at && (
          <p className="hint">
            Последнее решение: {a.reviewed_by ?? "—"}, {formatDate(a.reviewed_at)}
            {a.review_comment && <> — «{a.review_comment}»</>}
          </p>
        )}
        {saved && <div className="alert-success">{saved}</div>}
        {canReview(me) ? (
          <div className="review-form">
            {!me.auth_enabled && (
              <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Ваше имя" aria-label="Ваше имя" />
            )}
            <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Комментарий (необязательно)" aria-label="Комментарий" className="grow" />
            <div className="review-actions">
              <button type="button" className="btn ok" disabled={busy} onClick={() => review("reviewed_normal")}>
                ✓ Нормальная
              </button>
              <button type="button" className="btn danger" disabled={busy} onClick={() => review("reviewed_suspicious")}>
                ⚠ Подозрительная
              </button>
              {a.status !== "needs_review" && a.status !== "normal" && (
                <button type="button" className="btn" disabled={busy} onClick={() => review("needs_review")}>
                  Вернуть на проверку
                </button>
              )}
            </div>
          </div>
        ) : (
          <p className="muted">Решения по операциям принимают аналитики и администраторы.</p>
        )}
      </div>

      <details className="card details">
        <summary>Как модель оценила операцию</summary>
        <p className="muted">Признаки, которые сильнее всего повлияли на оценку аномальности.</p>
        <FactorBars factors={a.factors} />
      </details>

      <div className="card">
        <div className="card-head">
          <h3>Операции клиента {tx.client_id}</h3>
          <a href={link("clients", tx.client_id)}>Профиль клиента →</a>
        </div>
        {client ? <ActivityChart items={client.recent} highlightId={tx.transaction_id} /> : <div className="muted">Загрузка…</div>}
        <ClientTransactions clientId={tx.client_id} highlightId={tx.transaction_id} reloadKey={reloadKey} />
      </div>
    </div>
  );
}
