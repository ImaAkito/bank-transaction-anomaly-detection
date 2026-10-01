import { useEffect, useState } from "react";
import { api } from "../api";
import { ActivityChart, BarList, HourHistogram } from "../components/Charts";
import { TransactionTable } from "../components/TransactionTable";
import { EVENT_LABELS, RISK_LABELS, formatDate, formatMoney, formatNumber } from "../format";
import { link } from "../router";
import type { AlertHistoryRow, ClientDetail, ClientRow, RiskLevel } from "../types";

export function ClientList() {
  const [rows, setRows] = useState<ClientRow[]>([]);
  const [search, setSearch] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.clients(search, onlyFlagged).then(setRows).catch((e: Error) => setError(e.message));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search, onlyFlagged]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Клиенты</h2>
        <div className="row">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по ID" />
          <label className="check">
            <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> только со срабатываниями
          </label>
        </div>
      </div>
      {error && <div className="alert-error">Ошибка: {error}</div>}
      {rows.length === 0 ? (
        <div className="empty">Клиентов нет</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Клиент</th>
                <th className="num">Операций</th>
                <th className="num">Срабатываний</th>
                <th className="num">Макс. оценка</th>
                <th>Последняя активность</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.client_id}>
                  <td>
                    <a href={link("clients", c.client_id)}>{c.client_id}</a>
                  </td>
                  <td className="num">{c.transactions}</td>
                  <td className="num">{c.flagged}</td>
                  <td className="num">{formatNumber(c.max_score, 2)}</td>
                  <td>{formatDate(c.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ClientPage({ id }: { id: string }) {
  const [client, setClient] = useState<ClientDetail | null>(null);
  const [alerts, setAlerts] = useState<AlertHistoryRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setClient(null);
    api.client(id).then(setClient).catch((e: Error) => setError(e.message));
    api.alerts(id).then(setAlerts).catch(() => setAlerts([]));
  }, [id]);

  if (error) return <div className="alert-error">Ошибка: {error}</div>;
  if (!client) return <div className="card">Загрузка…</div>;
  const p = client.profile;

  return (
    <div className="stack">
      <div className="card">
        <div className="muted">
          <a href="#/clients">← К списку клиентов</a>
        </div>
        <h2>Клиент {client.client_id}</h2>
        <div className="muted">
          Часовой пояс: {client.timezone} · первая операция в системе: {formatDate(client.first_seen)} · последняя активность: {formatDate(client.last_seen)}
        </div>
      </div>

      <div className="cards">
        <div className="card stat">
          <div className="stat-label">Медианная сумма</div>
          <div className="stat-value small">{p.median_amount ? formatMoney(p.median_amount, "RUB") : "—"}</div>
          <div className="muted">90-й процентиль: {p.p90_amount ? formatMoney(p.p90_amount, "RUB") : "—"}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Операций в профиле</div>
          <div className="stat-value small">{p.transactions_in_profile}</div>
          <div className="muted">всего получено: {p.transactions_seen}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Интенсивность</div>
          <div className="stat-value small">{formatNumber(p.avg_transactions_per_day, 1)}</div>
          <div className="muted">операций в сутки</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Известных получателей</div>
          <div className="stat-value small">{p.known_recipients}</div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Профиль: часы активности</h3>
          <HourHistogram counts={p.hour_counts} typical={p.typical_hours} />
          <div className="muted">Выделены часы, покрывающие 80% операций клиента</div>
        </div>
        <div className="card">
          <h3>Профиль: категории и каналы</h3>
          <BarList data={p.categories} />
          <div className="spacer" />
          <BarList data={p.channels} />
        </div>
      </div>

      <div className="card">
        <h3>История активности</h3>
        <ActivityChart items={client.recent} />
        <div className="legend">
          {(Object.keys(RISK_LABELS) as RiskLevel[]).map((l) => (
            <span key={l} className="legend-item">
              <span className={`dot dot-${l}`} /> риск {RISK_LABELS[l]}
            </span>
          ))}
        </div>
        <TransactionTable items={client.recent.slice(0, 30)} showClient={false} />
      </div>

      <div className="card">
        <h3>История срабатываний</h3>
        {alerts.length === 0 ? (
          <div className="empty">Срабатываний нет</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Событие</th>
                  <th>Операция</th>
                  <th>Риск</th>
                  <th>Статус</th>
                  <th>Специалист</th>
                  <th>Комментарий</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((h) => (
                  <tr key={h.id}>
                    <td className="nowrap">{formatDate(h.created_at)}</td>
                    <td>{EVENT_LABELS[h.event_type] ?? h.event_type}</td>
                    <td>
                      <a href={link("transactions", h.transaction_id)} className="mono">
                        {h.transaction_id}
                      </a>
                    </td>
                    <td>{RISK_LABELS[h.risk_level as RiskLevel] ?? h.risk_level}</td>
                    <td>{h.status}</td>
                    <td>{h.actor ?? "—"}</td>
                    <td>{h.comment ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
