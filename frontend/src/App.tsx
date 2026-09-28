import { ClientList, ClientPage } from "./pages/Clients";
import { Dashboard } from "./pages/Dashboard";
import { ModelPage } from "./pages/ModelPage";
import { TransactionDetail } from "./pages/TransactionDetail";
import { Transactions } from "./pages/Transactions";
import { useRoute } from "./router";

const NAV = [
  { key: "", label: "Онлайн-поток" },
  { key: "transactions", label: "Транзакции" },
  { key: "clients", label: "Клиенты" },
  { key: "model", label: "Модель" },
];

export function App() {
  const route = useRoute();
  const [section, id] = route;

  let page;
  if (!section) page = <Dashboard />;
  else if (section === "transactions" && id) page = <TransactionDetail id={id} key={id} />;
  else if (section === "transactions") page = <Transactions />;
  else if (section === "clients" && id) page = <ClientPage id={id} key={id} />;
  else if (section === "clients") page = <ClientList />;
  else if (section === "model") page = <ModelPage />;
  else page = <div className="card">Страница не найдена</div>;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          Аномальные транзакции
        </div>
        <nav>
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className={(section ?? "") === n.key ? "active" : ""}>
              {n.label}
            </a>
          ))}
        </nav>
      </header>
      <main>{page}</main>
    </div>
  );
}
