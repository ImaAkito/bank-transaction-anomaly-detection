import { useEffect, useState } from "react";
import { api, type TransactionFilters } from "../api";
import { Filters } from "../components/Filters";
import { Pager } from "../components/Pager";
import { TransactionTable } from "../components/TransactionTable";
import { formatNumber } from "../format";
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
  const [loading, setLoading] = useState(true);
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

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Операции</h1>
          <p className="muted">По умолчанию показаны операции со средним и высоким риском — их стоит проверить в первую очередь.</p>
        </div>
      </div>
      <Filters value={filters} onChange={setFilters} onReset={() => setFilters(initial)} />
      {error && <div className="alert-error">Не удалось загрузить операции: {error}</div>}
      <div className="card">
        <div className="toolbar">
          <span className="muted">{loading ? "Загрузка…" : `Найдено: ${formatNumber(total, 0)}`}</span>
        </div>
        <TransactionTable items={items} empty="По выбранным условиям операций нет — попробуйте изменить фильтры" />
        <Pager total={total} limit={filters.limit} offset={filters.offset} onChange={(offset) => setFilters({ ...filters, offset })} />
      </div>
    </div>
  );
}
