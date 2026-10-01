import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { formatDate } from "../format";
import type { UserRow } from "../types";

const ROLE_LABELS: Record<string, string> = {
  viewer: "Наблюдатель (только просмотр)",
  analyst: "Аналитик (просмотр и решения)",
  admin: "Администратор",
};

export function Users() {
  const [rows, setRows] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", password: "", role: "analyst" });

  const load = () => api.users().then(setRows).catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api.createUser(form.username, form.password, form.role);
      setForm({ username: "", password: "", role: "analyst" });
      setError(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const update = async (username: string, patch: { active?: boolean; role?: string }) => {
    try {
      await api.updateUser(username, patch);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="stack">
      {error && <div className="alert-error">{error}</div>}
      <div className="card">
        <h2>Пользователи</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Имя</th>
                <th>Роль</th>
                <th>Статус</th>
                <th>Создан</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.username}>
                  <td>{u.username}</td>
                  <td>
                    <select value={u.role} onChange={(e) => update(u.username, { role: e.target.value })}>
                      {Object.entries(ROLE_LABELS).map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{u.active ? "активен" : "отключён"}</td>
                  <td>{formatDate(u.created_at)}</td>
                  <td>
                    <button type="button" className="btn" onClick={() => update(u.username, { active: !u.active })}>
                      {u.active ? "Отключить" : "Включить"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <form className="card review-form" onSubmit={create}>
        <h3 style={{ width: "100%" }}>Новый пользователь</h3>
        <input placeholder="Имя" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        <input placeholder="Пароль (не короче 6 символов)" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          {Object.entries(ROLE_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <button type="submit" className="btn primary" disabled={form.username.length < 3 || form.password.length < 6}>
          Создать
        </button>
      </form>
    </div>
  );
}
