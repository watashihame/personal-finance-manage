/* global React, ReactDOM */
// Main app entry point: auth check → data load → render variant B.

const { useState, useEffect } = React;

function VariantApp({ variant, dataVersion, theme, onToggleTheme }) {
  const [page, setPage] = useState("dashboard");
  const [params, setParams] = useState({});

  const navigate = (p, q = {}) => { setPage(p); setParams(q); };

  const Dashboard = variant === "a" ? DashboardA : variant === "b" ? DashboardB : DashboardC;

  let content;
  if (page === "dashboard")    content = <Dashboard />;
  else if (page === "holdings")     content = <HoldingsPage />;
  else if (page === "trends")       content = <TrendsPage />;
  else if (page === "transactions") content = <TransactionsPage params={params} />;
  else if (page === "add")          content = <AddHoldingPage />;
  else content = <Dashboard />;

  return (
    <RouteCtx.Provider value={{ page, navigate, params, setPage }}>
      <div style={{
        minHeight: "100%", display: "flex", flexDirection: "column",
        background: "var(--bg)", color: "var(--fg)",
      }}>
        <Navbar variant={variant.toUpperCase()} dataVersion={dataVersion} theme={theme} onToggleTheme={onToggleTheme} />
        <main style={{ flex: 1, position: "relative" }}>
          <div key={page + variant + dataVersion}>{content}</div>
        </main>
        <StatusBar variant={variant} />
      </div>
    </RouteCtx.Provider>
  );
}
const RouteCtx = window.RouteCtx || React.createContext(null);
window.RouteCtx = RouteCtx;

function LoadingScreen() {
  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center", background: "var(--bg)",
      fontFamily: "var(--font-mono)", fontSize: 12,
      color: "var(--fg-3)", letterSpacing: "0.1em",
    }}>
      LOADING…
    </div>
  );
}

function ErrorScreen({ message }) {
  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center",
      justifyContent: "center", background: "var(--bg)", padding: 24,
    }}>
      <div style={{
        maxWidth: 420, textAlign: "center",
        fontFamily: "var(--font-mono)", color: "var(--fg-2)",
      }}>
        <div style={{ fontSize: 28, marginBottom: 12 }}>⚠</div>
        <div style={{ fontSize: 13, marginBottom: 8 }}>加载失败</div>
        <div style={{ fontSize: 11, color: "var(--fg-3)" }}>{message}</div>
        <button className="btn sm" style={{ marginTop: 20 }} onClick={() => location.reload()}>重试</button>
      </div>
    </div>
  );
}

function _getSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function App() {
  const [status, setStatus] = useState("loading");
  const [errorMsg, setErrorMsg] = useState("");
  const [dataVersion, setDataVersion] = useState(0);

  // Theme: localStorage override → system default
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || _getSystemTheme());

  // Apply theme to DOM whenever it changes
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Follow system changes unless user has manually overridden
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handle = e => {
      if (!localStorage.getItem("theme")) {
        setTheme(e.matches ? "dark" : "light");
      }
    };
    mq.addEventListener("change", handle);
    return () => mq.removeEventListener("change", handle);
  }, []);

  const toggleTheme = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    localStorage.setItem("theme", next);
  };

  const loadData = () =>
    window.initFromAPI()
      .then(() => { setDataVersion(v => v + 1); setStatus("ready"); })
      .catch(err => { setErrorMsg(err.message); setStatus("error"); });

  useEffect(() => {
    fetch("/api/auth/status")
      .then(r => r.json())
      .then(d => {
        if (d.authenticated) return loadData();
        setStatus("login");
      })
      .catch(err => { setErrorMsg(err.message); setStatus("error"); });
  }, []);

  useEffect(() => {
    const onRefresh = () => loadData();
    window.addEventListener("portfolio-refreshed", onRefresh);
    return () => window.removeEventListener("portfolio-refreshed", onRefresh);
  }, []);

  if (status === "loading") return <LoadingScreen />;
  if (status === "error")   return <ErrorScreen message={errorMsg} />;
  if (status === "login")   return (
    <LoginPage onLogin={token => {
      fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      })
        .then(r => r.ok ? loadData() : r.json().then(d => { throw new Error(d.error || "登录失败"); }))
        .catch(err => alert(err.message));
    }} />
  );

  return <VariantApp variant="b" dataVersion={dataVersion} theme={theme} onToggleTheme={toggleTheme} />;
}

window.App = App;
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
