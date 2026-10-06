import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { TransactionTable } from "../components/TransactionTable";
import { formatNumber, formatPercent } from "../format";
import type { LiveEvent, Stats, Transaction } from "../types";
import { useLiveFeed } from "../useLiveFeed";

const FEED_LIMIT = 100;

export function Dashboard() {
  const [feed, setFeed] = useState<Transaction[]>([]);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [stats, setStats] = useState<Stats | null>(null);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pausedRef = useRef(false);
  pausedRef.current = paused;

  const loadStats = useCallback(() => {
    api.stats().then(setStats).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    api
      .transactions({ limit: 40, sort: "received", order: "desc" })
      .then((page) => setFeed(page.items))
      .catch((e: Error) => setError(e.message));
    loadStats();
    const timer = window.setInterval(loadStats, 5000);
    return () => window.clearInterval(timer);
  }, [loadStats]);

  const onEvent = useCallback((event: LiveEvent) => {
    const tx = event.data;
    if (event.type === "transaction_reviewed") {
      setFeed((prev) => prev.map((t) => (t.transaction_id === tx.transaction_id ? tx : t)));
      return;
    }
    if (pausedRef.current) return;
    setFeed((prev) => [tx, ...prev.filter((t) => t.transaction_id !== tx.transaction_id)].slice(0, FEED_LIMIT));
    setFresh((prev) => new Set(prev).add(tx.transaction_id));
    window.setTimeout(
      () =>
        setFresh((prev) => {
          const next = new Set(prev);
          next.delete(tx.transaction_id);
          return next;
        }),
      2500,
    );
  }, []);
  const connection = useLiveFeed(onEvent);

  const visible = onlyFlagged ? feed.filter((t) => t.analysis.risk_level !== "low") : feed;
  const sim = stats?.simulation_check;
  const waiting = stats?.by_status.needs_review ?? 0;

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Онлайн-поток</h1>
          <p className="muted">Операции появляются здесь сразу после анализа.</p>
        </div>
        <span className={`conn conn-${connection}`}>
          <span className="dot" />
          {connection === "open" ? "Подключено" : connection === "connecting" ? "Подключение…" : "Нет связи с сервером"}
        </span>
      </div>
      {error && <div className="alert-error">Не удалось загрузить данные: {error}</div>}

      <div className="cards">
        <a className="card stat stat-link" href="#/transactions">
          <div className="stat-label">Ждут проверки</div>
          <div className={`stat-value ${waiting > 0 ? "risk-text-medium" : ""}`}>{stats ? formatNumber(waiting, 0) : "—"}</div>
          <div className="muted">Открыть список →</div>
        </a>
        <div className="card stat">
          <div className="stat-label">Высокий риск</div>
          <div className="stat-value risk-text-high">{stats ? formatNumber(stats.by_risk.high ?? 0, 0) : "—"}</div>
          <div className="muted">средний: {stats ? formatNumber(stats.by_risk.medium ?? 0, 0) : "—"}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Всего операций</div>
          <div className="stat-value">{stats ? formatNumber(stats.total_transactions, 0) : "—"}</div>
          <div className="muted">
            клиентов: {stats ? formatNumber(stats.clients, 0) : "—"} · отмечено {stats ? formatPercent(stats.flagged_share) : "—"}
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">За последнюю минуту</div>
          <div className="stat-value">{stats ? formatNumber(stats.transactions_last_minute, 0) : "—"}</div>
          <div className="muted">анализ одной операции: {stats ? formatNumber(stats.avg_latency_ms, 0) : "—"} мс</div>
        </div>
        {sim && sim.precision !== null && sim.recall !== null && (
          <div className="card stat" title="Демонстрационные операции заранее размечены симулятором; сравнение показывает качество выявления">
            <div className="stat-label">Качество на демо-данных</div>
            <div className="stat-value small">
              найдено {formatPercent(sim.recall, 0)} аномалий
            </div>
            <div className="muted">верных срабатываний: {formatPercent(sim.precision, 0)}</div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="toolbar">
          <div className="segmented" role="group" aria-label="Какие операции показать">
            <button type="button" className={!onlyFlagged ? "on" : ""} onClick={() => setOnlyFlagged(false)}>
              Все операции
            </button>
            <button type="button" className={onlyFlagged ? "on" : ""} onClick={() => setOnlyFlagged(true)}>
              Требующие внимания
            </button>
          </div>
          <button type="button" className="btn" onClick={() => setPaused((p) => !p)}>
            {paused ? "▶ Продолжить" : "❚❚ Пауза"}
          </button>
        </div>
        {paused && <p className="hint">Поток приостановлен: новые операции продолжают анализироваться, но не добавляются в список.</p>}
        <TransactionTable
          items={visible}
          freshIds={fresh}
          empty={onlyFlagged ? "Среди последних операций нет требующих внимания" : "Ожидание операций… Убедитесь, что симулятор запущен"}
        />
      </div>
    </div>
  );
}
