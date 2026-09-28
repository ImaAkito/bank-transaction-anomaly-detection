import { RISK_LABELS, STATUS_LABELS } from "../format";
import type { TransactionFilters } from "../api";

interface Props {
  value: TransactionFilters;
  onChange: (next: TransactionFilters) => void;
}

export function Filters({ value, onChange }: Props) {
  const set = (patch: Partial<TransactionFilters>) => onChange({ ...value, ...patch, offset: 0 });
  const toggleRisk = (level: string) =>
    set({ risk: value.risk.includes(level) ? value.risk.filter((r) => r !== level) : [...value.risk, level] });
  return (
    <div className="filters card">
      <div className="filter">
        <label>Уровень риска</label>
        <div className="chips">
          {(Object.keys(RISK_LABELS) as (keyof typeof RISK_LABELS)[]).map((level) => (
            <button
              key={level}
              type="button"
              className={`chip risk-${level} ${value.risk.includes(level) ? "on" : ""}`}
              onClick={() => toggleRisk(level)}
            >
              {RISK_LABELS[level]}
            </button>
          ))}
        </div>
      </div>
      <div className="filter">
        <label>Статус</label>
        <select value={value.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Все</option>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="filter grow">
        <label>Поиск (ID клиента или операции)</label>
        <input value={value.search} placeholder="например, C00012" onChange={(e) => set({ search: e.target.value })} />
      </div>
      <div className="filter">
        <label>Категория</label>
        <input value={value.category} placeholder="groceries" onChange={(e) => set({ category: e.target.value })} />
      </div>
      <div className="filter">
        <label>Оценка не ниже: {value.min_score.toFixed(2)}</label>
        <input type="range" min={0} max={1} step={0.05} value={value.min_score} onChange={(e) => set({ min_score: Number(e.target.value) })} />
      </div>
      <div className="filter">
        <label>Сортировка</label>
        <select
          value={`${value.sort}:${value.order}`}
          onChange={(e) => {
            const [sort, order] = e.target.value.split(":") as [TransactionFilters["sort"], TransactionFilters["order"]];
            set({ sort, order });
          }}
        >
          <option value="received:desc">Сначала новые (поступление)</option>
          <option value="timestamp:desc">Сначала новые (время операции)</option>
          <option value="score:desc">Сначала высокая оценка</option>
          <option value="score:asc">Сначала низкая оценка</option>
        </select>
      </div>
    </div>
  );
}
