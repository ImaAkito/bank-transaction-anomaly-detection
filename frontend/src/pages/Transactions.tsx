import { useEffect, useState } from "react";
import { api, type TransactionFilters } from "../api";
import { Filters } from "../components/Filters";
import { TransactionTable } from "../components/TransactionTable";
import type { Transaction } from "../types";

const initial: TransactionFilters = {
  risk: ["medium", "high"],
  status: "",
  client_id: "",
  search: "",
  min_score: 0,
  category: "",
  only_flagged: false,
  sort: "received",
  order: "desc",
  limit: 25,
  offset: 0,
};

export function Transactions() {
  const [filters, setFilters] = useState<TransactionFilters>(initial);
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      api
        .transactions(filters)
        .then((page) => {
          if (cancelled) return;
          setItems(page.items);
          setTotal(page.total);
          setError(null);
        })
        .catch((e: Error) => !cancelled && setError(e.message))
        .finally(() => !cancelled && setLoading(false));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [filters]);

  const pages = Math.max(1, Math.ceil(total / filters.limit));
  const page = Math.floor(filters.offset / filters.limit) + 1;

  return (
    <div className="stack">
      <Filters value={filters} onChange={setFilters} />
      {error && <div className="alert-error">Ошибка загрузки: {error}</div>}
      <div className="card">
        <div className="card-head">
          <h2>Транзакции</h2>
          <span className="muted">{loading ? "загрузка…" : `найдено: ${total}`}</span>
        </div>
        <TransactionTable items={items} empty="По выбранным условиям транзакций нет" />
        <div className="pager">
          <button type="button" className="btn" disabled={page <= 1} onClick={() => setFilters({ ...filters, offset: filters.offset - filters.limit })}>
            ← Назад
          </button>
          <span>
            Страница {page} из {pages}
          </span>
          <button type="button" className="btn" disabled={page >= pages} onClick={() => setFilters({ ...filters, offset: filters.offset + filters.limit })}>
            Вперёд →
          </button>
        </div>
      </div>
    </div>
  );
}
