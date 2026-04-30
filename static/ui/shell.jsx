/* global React, ReactDOM */
// Shared shell: navbar, theme provider, layout. Used by all variants.

const { useState, useEffect, createContext, useContext, useMemo } = React;

// ---- Theme context ----
const ThemeCtx = React.createContext(null);

function ThemeProvider({ children, defaults }) {
  const [theme, setTheme] = useState(defaults.theme);
  const [pnl, setPnl] = useState(defaults.pnl);
  const [density, setDensity] = useState(defaults.density);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-pnl", pnl);
    document.documentElement.setAttribute("data-density", density);
  }, [theme, pnl, density]);

  const value = useMemo(() => ({ theme, setTheme, pnl, setPnl, density, setDensity }), [theme, pnl, density]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}
const useTheme = () => useContext(ThemeCtx);

// ---- Router (very simple, page-level) ----
const RouteCtx = React.createContext(null);
function Router({ children, initial = "dashboard" }) {
  const [page, setPage] = useState(initial);
  const [params, setParams] = useState({});
  const navigate = (p, q = {}) => { setPage(p); setParams(q); };
  return <RouteCtx.Provider value={{ page, setPage, params, navigate }}>{children}</RouteCtx.Provider>;
}
const useRoute = () => useContext(RouteCtx);

// ---- Top navbar ----
function Navbar({ variant, dataVersion, theme, onToggleTheme }) {
  const { page, navigate } = useRoute();
  const items = [
    { id: "dashboard",    label: "仪表盘" },
    { id: "holdings",     label: "持仓列表" },
    { id: "trends",       label: "趋势分析" },
    { id: "transactions", label: "交易记录" },
    { id: "add",          label: "+ 添加持仓" },
  ];
  return (
    <header style={{
      display: "flex",
      alignItems: "center",
      gap: 24,
      padding: "0 24px",
      height: 52,
      background: "var(--surface)",
      borderBottom: "1px solid var(--border)",
      position: "sticky",
      top: 0,
      zIndex: 50,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <BrandMark />
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
          <span style={{ fontWeight: 600, fontSize: "var(--fs-sm)", letterSpacing: "0.01em" }}>持仓追踪</span>
          <span className="mono" style={{ fontSize: 9, color: "var(--fg-3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>portfolio · v{variant}</span>
        </div>
      </div>
      <nav style={{ display: "flex", gap: 2 }}>
        {items.map(it => (
          <button
            key={it.id}
            onClick={() => navigate(it.id)}
            style={{
              border: 0,
              background: "transparent",
              color: page === it.id ? "var(--fg)" : "var(--fg-2)",
              fontSize: "var(--fs-sm)",
              padding: "6px 10px",
              cursor: "pointer",
              borderRadius: "var(--r-2)",
              fontWeight: page === it.id ? 500 : 400,
              position: "relative",
              transition: "color var(--transition-fast)",
            }}
            onMouseEnter={e => e.currentTarget.style.color = "var(--fg)"}
            onMouseLeave={e => e.currentTarget.style.color = page === it.id ? "var(--fg)" : "var(--fg-2)"}
          >
            {it.label}
            {page === it.id && (
              <span style={{
                position: "absolute", left: 10, right: 10, bottom: -14, height: 2,
                background: "var(--fg)", borderRadius: 1,
              }} />
            )}
          </button>
        ))}
      </nav>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--fg-3)" }}>
          USD/CNY <span style={{ color: "var(--fg-1)" }}>{FX.USD.toFixed(3)}</span>
          <span style={{ margin: "0 8px", opacity: 0.4 }}>·</span>
          JPY/CNY <span style={{ color: "var(--fg-1)" }}>{FX.JPY.toFixed(4)}</span>
        </span>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        <RefreshButton />
      </div>
    </header>
  );
}

function BrandMark() {
  return (
    <div style={{
      width: 24, height: 24, borderRadius: 4,
      background: "var(--fg)",
      display: "flex", alignItems: "center", justifyContent: "center",
      color: "var(--bg)",
      fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700,
      letterSpacing: "-0.04em",
    }}>
      $
    </div>
  );
}

// ---- Status bar (bottom) ----
function StatusBar({ variant }) {
  const root = document.documentElement;
  const theme = root.getAttribute("data-theme") || "light";
  const pnl = root.getAttribute("data-pnl") || "red-up";
  const density = root.getAttribute("data-density") || "standard";
  const now = new Date();
  const stamp = now.toISOString().replace("T", " ").slice(0, 19);
  return (
    <div style={{
      borderTop: "1px solid var(--border)",
      background: "var(--surface)",
      padding: "0 16px",
      height: 24,
      display: "flex",
      alignItems: "center",
      gap: 16,
      fontFamily: "var(--font-mono)",
      fontSize: 10,
      color: "var(--fg-3)",
      letterSpacing: "0.04em",
    }}>
      <span>VARIANT <span style={{ color: "var(--fg-1)" }}>{variant.toUpperCase()}</span></span>
      <span>·</span>
      <span>THEME <span style={{ color: "var(--fg-1)" }}>{theme}</span></span>
      <span>·</span>
      <span>DENSITY <span style={{ color: "var(--fg-1)" }}>{density}</span></span>
      <span>·</span>
      <span>PNL <span style={{ color: "var(--fg-1)" }}>{pnl}</span></span>
      <span style={{ marginLeft: "auto" }}>LAST SYNC <span style={{ color: "var(--fg-1)" }}>{stamp}</span></span>
    </div>
  );
}

function ThemeToggle({ theme, onToggle }) {
  const isDark = theme === "dark";
  return (
    <button
      className="btn sm"
      onClick={onToggle}
      title={isDark ? "切换到浅色模式" : "切换到深色模式"}
      style={{ minWidth: 32, padding: "0 8px" }}
    >
      <span style={{ fontSize: 14, lineHeight: 1 }}>{isDark ? "☀" : "☾"}</span>
    </button>
  );
}

function RefreshButton() {
  const [loading, setLoading] = useState(false);
  const handleClick = async () => {
    setLoading(true);
    try {
      await fetch("/api/refresh-prices", { method: "POST" });
      window.dispatchEvent(new Event("portfolio-refreshed"));
    } catch (e) {
      alert("刷新失败: " + e);
    } finally {
      setLoading(false);
    }
  };
  return (
    <button className="btn sm" onClick={handleClick} disabled={loading}>
      <span style={{ fontFamily: "var(--font-mono)" }}>{loading ? "…" : "↻"}</span> 刷新
    </button>
  );
}

Object.assign(window, { ThemeProvider, useTheme, Router, useRoute, Navbar, StatusBar, BrandMark, RefreshButton, ThemeToggle });
