import type { TransactionFilters } from "../api";
import { RISK_LABELS, STATUS_LABELS, formatNumber } from "../format";
import { CATEGORY_LABELS } from "../labels";

interface Props {
  value: TransactionFilters;
  onChange: (next: TransactionFilters) => void;
  onReset: () => void;
}

const SIMULATED_CATEGORIES = [
  "groceries", "restaurants", "transport", "utilities", "entertainment", "health", "clothing", "p2p_transfer",
  "online_shopping", "travel", "education", "cash_withdrawal", "electronics", "jewelry", "crypto_exchange", "gambling",
];

export function Filters({ value, onChange, onReset }: Props) {
  const set = (patch: Partial<TransactionFilters>) => onChange({ ...value, ...patch, offset: 0 });
  const toggleRisk = (level: string) =>
    set({ risk: value.risk.includes(level) ? value.risk.filter((r) => r !== level) : [...value.risk, level] });
  return (
    <div className="filters card">
      <div className="filter grow">
        <label htmlFor="f-search">Поиск</label>
        <input id="f-search" value={value.search} placeholder="Номер клиента или операции" onChange={(e) => set({ search: e.target.value })} />
      </div>
      <div className="filter">
        <label>Уровень риска</label>
        <div className="chips">
          {(Object.keys(RISK_LABELS) as (keyof typeof RISK_LABELS)[]).map((level) => (
            <button
              key={level}
              type="button"
              className={`chip risk-${level} ${value.risk.includes(level) ? "on" : ""}`}
              onClick={() => toggleRisk(level)}
              aria-pressed={value.risk.includes(level)}
            >
              {RISK_LABELS[level]}
            </button>
          ))}
        </div>
      </div>
      <div className="filter">
        <label htmlFor="f-status">Статус</label>
        <select id="f-status" value={value.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Любой</option>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="filter">
        <label htmlFor="f-category">Категория</label>
        <select id="f-category" value={value.category} onChange={(e) => set({ category: e.target.value })}>
          <option value="">Любая</option>
          {SIMULATED_CATEGORIES.map((code) => (
            <option key={code} value={code}>
              {CATEGORY_LABELS[code]}
            </option>
          ))}
        </select>
      </div>
      <div className="filter">
        <label htmlFor="f-score">Оценка от {formatNumber(value.min_score, 2)}</label>
        <input id="f-score" type="range" min={0} max={1} step={0.05} value={value.min_score} onChange={(e) => set({ min_score: Number(e.target.value) })} />
      </div>
      <div className="filter">
        <label htmlFor="f-sort">Сортировка</label>
        <select
          id="f-sort"
          value={`${value.sort}:${value.order}`}
          onChange={(e) => {
            const [sort, order] = e.target.value.split(":") as [TransactionFilters["sort"], TransactionFilters["order"]];
            set({ sort, order });
          }}
        >
          <option value="received:desc">Сначала последние поступившие</option>
          <option value="timestamp:desc">Сначала новые по дате операции</option>
          <option value="score:desc">Сначала с высокой оценкой</option>
          <option value="score:asc">Сначала с низкой оценкой</option>
        </select>
      </div>
      <button type="button" className="btn link-btn" onClick={onReset}>
        Сбросить
      </button>
    </div>
  );
}
