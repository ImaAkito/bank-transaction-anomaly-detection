import { useState, type FormEvent } from "react";
import { api } from "../api";
import { setToken } from "../auth";

export function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(username, password);
      setToken(result.access_token);
      onLogin();
    } catch {
      setError("Неверное имя пользователя или пароль");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark" />
          Аномальные транзакции
        </div>
        <p className="muted">Вход для специалистов</p>
        <label className="field">
          <span>Имя пользователя</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label className="field">
          <span>Пароль</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error && <div className="alert-error">{error}</div>}
        <button type="submit" className="btn primary" disabled={busy || !username || !password}>
          {busy ? "Вход…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
