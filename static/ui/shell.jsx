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

function useIsMobile(breakpoint = 760) {
  const query = `(max-width: ${breakpoint}px)`;
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = e => setMatches(e.matches);
    setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

// ---- Top navbar ----
function Navbar({ variant, dataVersion, theme, onToggleTheme }) {
  const { page, navigate } = useRoute();
  const mobile = useIsMobile();
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
      flexWrap: mobile ? "wrap" : "nowrap",
      gap: mobile ? 10 : 24,
      padding: mobile ? "10px 12px" : "0 24px",
      minHeight: mobile ? 0 : 52,
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
      <nav style={{
        display: "flex",
        gap: 2,
        order: mobile ? 3 : 0,
        width: mobile ? "100%" : "auto",
        overflowX: mobile ? "auto" : "visible",
        paddingBottom: mobile ? 2 : 0,
        WebkitOverflowScrolling: "touch",
      }}>
        {items.map(it => (
          <button
            key={it.id}
            onClick={() => navigate(it.id)}
            style={{
              border: 0,
              background: "transparent",
              color: page === it.id ? "var(--fg)" : "var(--fg-2)",
              fontSize: "var(--fs-sm)",
              padding: mobile ? "7px 10px" : "6px 10px",
              cursor: "pointer",
              borderRadius: "var(--r-2)",
              fontWeight: page === it.id ? 500 : 400,
              position: "relative",
              transition: "color var(--transition-fast)",
              whiteSpace: "nowrap",
            }}
            onMouseEnter={e => e.currentTarget.style.color = "var(--fg)"}
            onMouseLeave={e => e.currentTarget.style.color = page === it.id ? "var(--fg)" : "var(--fg-2)"}
          >
            {it.label}
            {page === it.id && (
              <span style={{
                position: "absolute", left: 10, right: 10, bottom: mobile ? -3 : -14, height: 2,
                background: "var(--fg)", borderRadius: 1,
              }} />
            )}
          </button>
        ))}
      </nav>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: mobile ? 8 : 12 }}>
        <span className="mono" style={{ display: mobile ? "none" : "inline", fontSize: 11, color: "var(--fg-3)" }}>
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
  const mobile = useIsMobile();
  if (mobile) return null;

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

const REFRESH_MARKETS = [
  { value: "all",    label: "全部" },
  { value: "cn",     label: "中国 (A股+基金+黄金)" },
  { value: "us",     label: "美股" },
  { value: "jp",     label: "日股" },
  { value: "crypto", label: "加密币" },
];

function RefreshButton() {
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [open]);

  const doRefresh = async (market) => {
    setLoading(true);
    setOpen(false);
    try {
      await fetch(`/api/refresh-prices?market=${encodeURIComponent(market)}`, { method: "POST" });
      window.dispatchEvent(new Event("portfolio-refreshed"));
    } catch (e) {
      alert("刷新失败: " + e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ position: "relative", display: "inline-flex" }} onClick={e => e.stopPropagation()}>
      <button
        className="btn sm"
        onClick={() => doRefresh("all")}
        disabled={loading}
        style={{ borderTopRightRadius: 0, borderBottomRightRadius: 0 }}
      >
        <span style={{ fontFamily: "var(--font-mono)" }}>{loading ? "…" : "↻"}</span> 刷新
      </button>
      <button
        className="btn sm"
        onClick={() => setOpen(v => !v)}
        disabled={loading}
        title="分市场刷新"
        style={{
          borderTopLeftRadius: 0,
          borderBottomLeftRadius: 0,
          borderLeft: 0,
          minWidth: 22,
          padding: "0 6px",
        }}
      >
        <span style={{ fontSize: 9 }}>▾</span>
      </button>
      {open && (
        <div style={{
          position: "absolute",
          top: "calc(100% + 4px)",
          right: 0,
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-2)",
          boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
          minWidth: 200,
          zIndex: 60,
          overflow: "hidden",
        }}>
          {REFRESH_MARKETS.map(m => (
            <button
              key={m.value}
              onClick={() => doRefresh(m.value)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                border: 0,
                background: "transparent",
                color: "var(--fg-1)",
                padding: "8px 12px",
                fontSize: "var(--fs-sm)",
                cursor: "pointer",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--surface-2, var(--border))"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { ThemeProvider, useTheme, Router, useRoute, useIsMobile, Navbar, StatusBar, BrandMark, RefreshButton, ThemeToggle });
