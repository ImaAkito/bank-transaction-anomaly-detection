import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { setToken, UnauthorizedError } from "./auth";
import { ClientList, ClientPage } from "./pages/Clients";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { ModelPage } from "./pages/ModelPage";
import { TransactionDetail } from "./pages/TransactionDetail";
import { Transactions } from "./pages/Transactions";
import { Users } from "./pages/Users";
import { useRoute } from "./router";
import { SessionContext } from "./session";
import type { Me } from "./types";

const NAV = [
  { key: "", label: "Онлайн-поток" },
  { key: "transactions", label: "Транзакции" },
  { key: "clients", label: "Клиенты" },
  { key: "model", label: "Модель" },
];

const ROLE_NAMES: Record<string, string> = { viewer: "наблюдатель", analyst: "аналитик", admin: "администратор" };

export function App() {
  const route = useRoute();
  const [section, id] = route;
  const [me, setMe] = useState<Me | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMe = useCallback(() => {
    api
      .me()
      .then((user) => {
        setMe(user);
        setNeedLogin(false);
      })
      .catch((e: Error) => {
        if (e instanceof UnauthorizedError) setNeedLogin(true);
        else setError(e.message);
      });
  }, []);

  useEffect(() => {
    loadMe();
    const handler = () => {
      setToken(null);
      setMe(null);
      setNeedLogin(true);
    };
    window.addEventListener("unauthorized", handler);
    return () => window.removeEventListener("unauthorized", handler);
  }, [loadMe]);

  if (needLogin) return <Login onLogin={loadMe} />;
  if (!me) return <div className="login-wrap">{error ? <div className="alert-error">Ошибка: {error}</div> : "Загрузка…"}</div>;

  let page;
  if (!section) page = <Dashboard />;
  else if (section === "transactions" && id) page = <TransactionDetail id={id} key={id} />;
  else if (section === "transactions") page = <Transactions />;
  else if (section === "clients" && id) page = <ClientPage id={id} key={id} />;
  else if (section === "clients") page = <ClientList />;
  else if (section === "model") page = <ModelPage />;
  else if (section === "users" && me.role === "admin" && me.auth_enabled) page = <Users />;
  else page = <div className="card">Страница не найдена</div>;

  const nav = me.auth_enabled && me.role === "admin" ? [...NAV, { key: "users", label: "Пользователи" }] : NAV;

  return (
    <SessionContext.Provider value={me}>
      <div className="app">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark" />
            Аномальные транзакции
          </div>
          <nav>
            {nav.map((n) => (
              <a key={n.key} href={`#/${n.key}`} className={(section ?? "") === n.key ? "active" : ""}>
                {n.label}
              </a>
            ))}
          </nav>
          {me.auth_enabled && (
            <div className="user-box">
              <span className="muted">
                {me.username} · {ROLE_NAMES[me.role] ?? me.role}
              </span>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setToken(null);
                  setMe(null);
                  setNeedLogin(true);
                }}
              >
                Выйти
              </button>
            </div>
          )}
        </header>
        <main>{page}</main>
      </div>
    </SessionContext.Provider>
  );
}
