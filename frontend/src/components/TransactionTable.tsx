import { categoryLabel, channelLabel } from "../labels";
import { link } from "../router";
import { formatDate, formatMoney, go } from "../format";
import type { Transaction } from "../types";
import { RiskBadge, ScoreBar, StatusBadge } from "./Badges";

interface Props {
  items: Transaction[];
  showClient?: boolean;
  highlightId?: string;
  freshIds?: Set<string>;
  empty?: string;
}

/** Таблица операций; строка целиком открывает карточку операции. */
export function TransactionTable({ items, showClient = true, highlightId, freshIds, empty }: Props) {
  if (items.length === 0) return <div className="empty">{empty ?? "Операций нет"}</div>;
  return (
    <div className="table-wrap">
      <table className="table-clickable">
        <thead>
          <tr>
            <th>Дата и время</th>
            {showClient && <th>Клиент</th>}
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
              onClick={() => go(link("transactions", t.transaction_id))}
              className={[
                t.transaction_id === highlightId ? "current" : "",
                freshIds?.has(t.transaction_id) ? "fresh" : "",
                t.analysis.risk_level !== "low" ? `flagged flagged-${t.analysis.risk_level}` : "",
              ].join(" ")}
            >
              <td className="nowrap">
                <a href={link("transactions", t.transaction_id)} onClick={(e) => e.stopPropagation()}>
                  {formatDate(t.timestamp)}
                </a>
              </td>
              {showClient && (
                <td>
                  <a href={link("clients", t.client_id)} onClick={(e) => e.stopPropagation()}>
                    {t.client_id}
                  </a>
                </td>
              )}
              <td className="num nowrap strong">{formatMoney(t.amount, t.currency)}</td>
              <td>{categoryLabel(t.category)}</td>
              <td className="muted-cell">{channelLabel(t.channel)}</td>
              <td style={{ minWidth: 120 }}>
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
