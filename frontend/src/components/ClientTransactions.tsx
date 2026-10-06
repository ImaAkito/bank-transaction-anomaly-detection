import { useEffect, useState } from "react";
import { api } from "../api";
import type { Transaction } from "../types";
import { Pager } from "./Pager";
import { TransactionTable } from "./TransactionTable";

const PAGE_SIZE = 15;

/** Все операции клиента с постраничным просмотром и фильтром «только требующие внимания». */
export function ClientTransactions({ clientId, highlightId, reloadKey = 0 }: { clientId: string; highlightId?: string; reloadKey?: number }) {
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .transactions({
        client_id: clientId,
        risk: onlyFlagged ? ["medium", "high"] : [],
        sort: "timestamp",
        order: "desc",
        limit: PAGE_SIZE,
        offset,
      })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [clientId, offset, onlyFlagged, reloadKey]);

  return (
    <div>
      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Какие операции показать">
          <button type="button" className={!onlyFlagged ? "on" : ""} onClick={() => { setOnlyFlagged(false); setOffset(0); }}>
            Все операции
          </button>
          <button type="button" className={onlyFlagged ? "on" : ""} onClick={() => { setOnlyFlagged(true); setOffset(0); }}>
            Требующие внимания
          </button>
        </div>
        <span className="muted">{loading ? "Загрузка…" : `Всего: ${total}`}</span>
      </div>
      {error && <div className="alert-error">Не удалось загрузить операции: {error}</div>}
      <TransactionTable
        items={items}
        showClient={false}
        highlightId={highlightId}
        empty={onlyFlagged ? "У клиента нет операций со средним или высоким риском" : "У клиента нет операций"}
      />
      <Pager total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
    </div>
  );
}
