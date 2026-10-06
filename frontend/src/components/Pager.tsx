interface Props {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}

/** Переключение страниц списка: «назад», номер страницы, «вперёд». */
export function Pager({ total, limit, offset, onChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;
  if (pages <= 1) return null;
  return (
    <div className="pager">
      <button type="button" className="btn" disabled={page <= 1} onClick={() => onChange(0)} aria-label="Первая страница">
        «
      </button>
      <button type="button" className="btn" disabled={page <= 1} onClick={() => onChange(offset - limit)}>
        ← Назад
      </button>
      <span className="pager-info">
        Страница {page} из {pages}
      </span>
      <button type="button" className="btn" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
        Вперёд →
      </button>
      <button type="button" className="btn" disabled={page >= pages} onClick={() => onChange((pages - 1) * limit)} aria-label="Последняя страница">
        »
      </button>
    </div>
  );
}
