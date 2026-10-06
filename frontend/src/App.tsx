import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { setToken, UnauthorizedError } from "./auth";
import { ROLE_NAMES } from "./format";
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
  { key: "transactions", label: "Операции" },
  { key: "clients", label: "Клиенты" },
  { key: "model", label: "Модель" },
];

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
        setError(null);
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

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [section, id]);

  if (needLogin) return <Login onLogin={loadMe} />;
  if (!me)
    return (
      <div className="login-wrap">
        {error ? (
          <div className="card login">
            <div className="alert-error">Не удалось подключиться к серверу: {error}</div>
            <button type="button" className="btn" onClick={loadMe}>
              Повторить
            </button>
          </div>
        ) : (
          <div className="muted">Загрузка…</div>
        )}
      </div>
    );

  let page;
  if (!section) page = <Dashboard />;
  else if (section === "transactions" && id) page = <TransactionDetail id={id} key={id} />;
  else if (section === "transactions") page = <Transactions />;
  else if (section === "clients" && id) page = <ClientPage id={id} key={id} />;
  else if (section === "clients") page = <ClientList />;
  else if (section === "model") page = <ModelPage />;
  else if (section === "users" && me.role === "admin" && me.auth_enabled) page = <Users />;
  else
    page = (
      <div className="card empty">
        Страница не найдена. <a href="#/">Вернуться к онлайн-потоку</a>
      </div>
    );

  const nav = me.auth_enabled && me.role === "admin" ? [...NAV, { key: "users", label: "Пользователи" }] : NAV;

  return (
    <SessionContext.Provider value={me}>
      <div className="app">
        <header className="topbar">
          <a className="brand" href="#/">
            <span className="brand-mark" />
            Мониторинг операций
          </a>
          <nav>
            {nav.map((n) => (
              <a key={n.key} href={`#/${n.key}`} className={(section ?? "") === n.key ? "active" : ""}>
                {n.label}
              </a>
            ))}
          </nav>
          {me.auth_enabled && (
            <div className="user-box">
              <span className="avatar" aria-hidden="true">
                {me.username.slice(0, 1).toUpperCase()}
              </span>
              <span className="user-name">
                {me.username}
                <span className="muted">{ROLE_NAMES[me.role] ?? me.role}</span>
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
