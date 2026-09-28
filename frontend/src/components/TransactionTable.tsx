import { link } from "../router";
import { formatDate, formatMoney } from "../format";
import type { Transaction } from "../types";
import { RiskBadge, ScoreBar, StatusBadge } from "./Badges";

interface Props {
  items: Transaction[];
  showClient?: boolean;
  highlightId?: string;
  freshIds?: Set<string>;
  empty?: string;
}

export function TransactionTable({ items, showClient = true, highlightId, freshIds, empty }: Props) {
  if (items.length === 0) return <div className="empty">{empty ?? "Транзакций нет"}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Время</th>
            {showClient && <th>Клиент</th>}
            <th>Операция</th>
            <th className="num">Сумма</th>
            <th>Категория</th>
            <th>Канал</th>
            <th>Оценка</th>
            <th>Риск</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr
              key={t.transaction_id}
              className={[
                t.transaction_id === highlightId ? "current" : "",
                freshIds?.has(t.transaction_id) ? "fresh" : "",
                t.analysis.risk_level !== "low" ? "flagged" : "",
              ].join(" ")}
            >
              <td className="nowrap">{formatDate(t.timestamp)}</td>
              {showClient && (
                <td>
                  <a href={link("clients", t.client_id)}>{t.client_id}</a>
                </td>
              )}
              <td>
                <a href={link("transactions", t.transaction_id)} className="mono">
                  {t.transaction_id}
                </a>
              </td>
              <td className="num nowrap">{formatMoney(t.amount, t.currency)}</td>
              <td>{t.category}</td>
              <td>{t.channel}</td>
              <td style={{ minWidth: 110 }}>
                <ScoreBar score={t.analysis.anomaly_score} level={t.analysis.risk_level} />
              </td>
              <td>
                <RiskBadge level={t.analysis.risk_level} />
              </td>
              <td>
                <StatusBadge status={t.analysis.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
