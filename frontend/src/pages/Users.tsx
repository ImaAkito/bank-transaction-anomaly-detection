import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ROLE_NAMES, formatDate } from "../format";
import { useSession } from "../session";
import type { UserRow } from "../types";

const ROLE_HINTS: Record<string, string> = {
  viewer: "только просмотр",
  analyst: "просмотр и решения по операциям",
  admin: "всё, включая пользователей и модель",
};
const ROLES = ["viewer", "analyst", "admin"] as const;

export function Users() {
  const me = useSession();
  const [rows, setRows] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", password: "", role: "analyst" });

  const load = () => api.users().then(setRows).catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api.createUser(form.username, form.password, form.role);
      setMessage(`Пользователь ${form.username} создан`);
      setForm({ username: "", password: "", role: "analyst" });
      setError(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const update = async (username: string, patch: { active?: boolean; role?: string }, done: string) => {
    try {
      await api.updateUser(username, patch);
      setMessage(done);
      setError(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Пользователи</h1>
          <p className="muted">Учётные записи специалистов и их права.</p>
        </div>
      </div>
      {error && <div className="alert-error">{error}</div>}
      {message && <div className="alert-success">{message}</div>}
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Имя</th>
                <th>Роль</th>
                <th>Состояние</th>
                <th>Создан</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const self = u.username === me.username;
                return (
                  <tr key={u.username}>
                    <td>
                      <strong>{u.username}</strong>
                      {self && <span className="tag">это вы</span>}
                    </td>
                    <td>
                      {self ? (
                        <span title="Собственную роль может изменить только другой администратор">{ROLE_NAMES[u.role]}</span>
                      ) : (
                        <select
                          value={u.role}
                          aria-label={`Роль пользователя ${u.username}`}
                          onChange={(e) => update(u.username, { role: e.target.value }, `Роль пользователя ${u.username} изменена`)}
                        >
                          {ROLES.map((role) => (
                            <option key={role} value={role}>
                              {ROLE_NAMES[role]}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td>{u.active ? <span className="state-on">активен</span> : <span className="state-off">отключён</span>}</td>
                    <td>{formatDate(u.created_at)}</td>
                    <td className="num">
                      {!self && (
                        <button
                          type="button"
                          className={`btn ${u.active ? "danger" : ""}`}
                          onClick={() =>
                            update(u.username, { active: !u.active }, `Пользователь ${u.username} ${u.active ? "отключён" : "включён"}`)
                          }
                        >
                          {u.active ? "Отключить" : "Включить"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="hint">Изменить собственную роль или отключить свою учётную запись нельзя — это может сделать другой администратор.</p>
      </div>

      <form className="card" onSubmit={create}>
        <h3>Новый пользователь</h3>
        <div className="form-grid">
          <label className="field">
            <span>Имя пользователя</span>
            <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="не короче 3 символов" />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="не короче 6 символов" />
          </label>
          <label className="field">
            <span>Роль</span>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {ROLE_NAMES[role]} — {ROLE_HINTS[role]}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn primary" disabled={form.username.length < 3 || form.password.length < 6}>
            Создать пользователя
          </button>
        </div>
      </form>
    </div>
  );
}
