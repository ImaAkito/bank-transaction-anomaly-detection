import { useEffect, useState } from "react";
import { api } from "../api";
import { ActivityChart, BarList, HourHistogram } from "../components/Charts";
import { ClientTransactions } from "../components/ClientTransactions";
import { EVENT_LABELS, RISK_LABELS, STATUS_LABELS, formatDate, formatDay, formatHourRanges, formatMoney, formatNumber, go } from "../format";
import { categoryLabel, channelLabel } from "../labels";
import { link } from "../router";
import type { AlertHistoryRow, ClientDetail, ClientRow, RiskLevel, Status } from "../types";

export function ClientList() {
  const [rows, setRows] = useState<ClientRow[] | null>(null);
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
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Клиенты</h1>
          <p className="muted">Профили поведения клиентов и операции, по которым сработала система.</p>
        </div>
      </div>
      <div className="card">
        <div className="toolbar">
          <input className="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по номеру клиента, например C00012" />
          <div className="segmented" role="group" aria-label="Каких клиентов показать">
            <button type="button" className={onlyFlagged ? "on" : ""} onClick={() => setOnlyFlagged(true)}>
              Со срабатываниями
            </button>
            <button type="button" className={!onlyFlagged ? "on" : ""} onClick={() => setOnlyFlagged(false)}>
              Все клиенты
            </button>
          </div>
        </div>
        {error && <div className="alert-error">Не удалось загрузить клиентов: {error}</div>}
        {rows === null ? (
          <div className="empty">Загрузка…</div>
        ) : rows.length === 0 ? (
          <div className="empty">{search ? "Клиент не найден" : "Клиентов со срабатываниями пока нет"}</div>
        ) : (
          <div className="table-wrap">
            <table className="table-clickable">
              <thead>
                <tr>
                  <th>Клиент</th>
                  <th className="num">Операций</th>
                  <th className="num">Требуют внимания</th>
                  <th className="num">Наибольшая оценка</th>
                  <th>Последняя операция</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.client_id} onClick={() => go(link("clients", c.client_id))}>
                    <td>
                      <a href={link("clients", c.client_id)} onClick={(e) => e.stopPropagation()}>
                        {c.client_id}
                      </a>
                    </td>
                    <td className="num">{c.transactions}</td>
                    <td className="num">{c.flagged > 0 ? <span className="count-flag">{c.flagged}</span> : "—"}</td>
                    <td className="num">{formatNumber(c.max_score, 2)}</td>
                    <td>{formatDate(c.last_seen)}</td>
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

export function ClientPage({ id }: { id: string }) {
  const [client, setClient] = useState<ClientDetail | null>(null);
  const [alerts, setAlerts] = useState<AlertHistoryRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setClient(null);
    api.client(id, 300).then(setClient).catch((e: Error) => setError(e.message));
    api.alerts(id).then(setAlerts).catch(() => setAlerts([]));
  }, [id]);

  if (error) return <div className="alert-error">Не удалось открыть профиль клиента: {error}</div>;
  if (!client) return <div className="card loading">Загрузка профиля…</div>;
  const p = client.profile;
  const topCategories = Object.keys(p.categories).slice(0, 3).map(categoryLabel);

  return (
    <div className="stack">
      <a href="#/clients" className="back-link">
        ← Все клиенты
      </a>
      <div className="page-head">
        <div>
          <h1>Клиент {client.client_id}</h1>
          <p className="muted">
            Клиент с {formatDay(client.first_seen)} · последняя операция {formatDate(client.last_seen)}
          </p>
        </div>
      </div>

      <div className="cards">
        <div className="card stat">
          <div className="stat-label">Обычная сумма операции</div>
          <div className="stat-value">{p.median_amount ? formatMoney(p.median_amount) : "—"}</div>
          <div className="muted">крупные: от {p.p90_amount ? formatMoney(p.p90_amount) : "—"}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Операций в среднем</div>
          <div className="stat-value">{formatNumber(p.avg_transactions_per_day, 1)}</div>
          <div className="muted">в сутки · всего {p.transactions_seen}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Обычное время</div>
          <div className="stat-value small">{formatHourRanges(p.typical_hours)}</div>
          <div className="muted">местное время клиента</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Чаще всего</div>
          <div className="stat-value small">{topCategories.join(", ") || "—"}</div>
          <div className="muted">постоянных получателей: {p.known_recipients}</div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Время активности</h3>
          <HourHistogram counts={p.hour_counts} typical={p.typical_hours} />
          <p className="hint">Выделены часы, на которые приходится большинство операций клиента.</p>
        </div>
        <div className="card">
          <h3>Категории и каналы</h3>
          <BarList data={p.categories} label={categoryLabel} limit={6} />
          <div className="spacer" />
          <BarList data={p.channels} label={channelLabel} limit={4} />
        </div>
      </div>

      <div className="card">
        <h3>Операции клиента</h3>
        <ActivityChart items={client.recent} />
        <div className="legend">
          {(Object.keys(RISK_LABELS) as RiskLevel[]).map((l) => (
            <span key={l} className="legend-item">
              <span className={`dot dot-${l}`} /> риск {RISK_LABELS[l]}
            </span>
          ))}
        </div>
        <ClientTransactions clientId={client.client_id} />
      </div>

      <div className="card">
        <h3>История срабатываний и решений</h3>
        {alerts.length === 0 ? (
          <div className="empty">Срабатываний не было</div>
        ) : (
          <div className="table-wrap">
            <table className="table-clickable">
              <thead>
                <tr>
                  <th>Дата и время</th>
                  <th>Событие</th>
                  <th>Риск</th>
                  <th>Статус</th>
                  <th>Кто</th>
                  <th>Комментарий</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((h) => (
                  <tr key={h.id} onClick={() => go(link("transactions", h.transaction_id))}>
                    <td className="nowrap">
                      <a href={link("transactions", h.transaction_id)} onClick={(e) => e.stopPropagation()}>
                        {formatDate(h.created_at)}
                      </a>
                    </td>
                    <td>{EVENT_LABELS[h.event_type] ?? h.event_type}</td>
                    <td>{RISK_LABELS[h.risk_level as RiskLevel] ?? h.risk_level}</td>
                    <td>{STATUS_LABELS[h.status as Status] ?? h.status}</td>
                    <td>{h.actor ?? (h.event_type === "triggered" ? "Система" : "—")}</td>
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
