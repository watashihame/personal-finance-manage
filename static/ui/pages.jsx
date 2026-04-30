/* global React */
// Other pages: holdings list, trends, transactions, add/edit, login.
// All variants share these — they re-skin only via tokens + density.

const { useState, useMemo, useEffect, useContext } = React;
const useRoute = () => useContext(window.RouteCtx);

// =============================================================
// Holdings list
// =============================================================
function HoldingsPage() {
  const allTags = useMemo(() => Array.from(new Set(HOLDINGS.flatMap(h => h.tags))).sort(), []);
  const [tagFilter, setTagFilter] = useState(null);
  const [marketFilter, setMarketFilter] = useState(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("valueCny");
  const [sortDir, setSortDir] = useState("desc");

  const filtered = useMemo(() => {
    let r = HOLDINGS;
    if (tagFilter) r = r.filter(h => h.tags.includes(tagFilter));
    if (marketFilter) r = r.filter(h => h.market === marketFilter);
    if (search) {
      const s = search.toLowerCase();
      r = r.filter(h => h.name.toLowerCase().includes(s) || h.symbol.toLowerCase().includes(s));
    }
    r = [...r].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return r;
  }, [tagFilter, marketFilter, search, sortKey, sortDir]);

  const totalValue = filtered.reduce((s, r) => s + r.valueCny, 0);
  const totalCost = filtered.reduce((s, r) => s + r.costCny, 0);
  const totalPnl = totalValue - totalCost;

  const toggleSort = k => {
    if (sortKey === k) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("desc"); }
  };

  const SortHeader = ({ k, children, align = "left" }) => (
    <th
      onClick={() => toggleSort(k)}
      className={align === "right" ? "num" : ""}
      style={{ cursor: "pointer", userSelect: "none" }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
        {children}
        <span style={{ color: sortKey === k ? "var(--fg)" : "var(--fg-4)", fontSize: 9 }}>
          {sortKey === k ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </span>
    </th>
  );

  const markets = ["CN", "US", "JP", "CRYPTO", "OTHER"];

  return (
    <PageWrap max={1500}>
      {/* Top bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 16, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "var(--fs-xl)", fontWeight: 600, letterSpacing: "-0.01em" }}>持仓列表</h2>
          <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em", marginTop: 2 }}>
            {filtered.length} OF {HOLDINGS.length} POSITIONS
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" placeholder="搜索名称或代码…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 220 }} />
          <button className="btn primary sm">+ 添加持仓</button>
        </div>
      </div>

      {/* Summary chips */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <SummaryChip label="总市值" value={fmt.cny(totalValue, 2)} />
        <SummaryChip label="总成本" value={fmt.cny(totalCost, 2)} muted />
        <SummaryChip label="浮盈" value={fmt.signed(totalPnl, 2)} color={totalPnl >= 0 ? "up" : "down"} />
        <SummaryChip label="盈亏率" value={fmt.pct((totalPnl / totalCost) * 100)} color={totalPnl >= 0 ? "up" : "down"} />
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 16, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <FilterRow label="市场">
          <FilterChip active={!marketFilter} onClick={() => setMarketFilter(null)}>全部</FilterChip>
          {markets.map(m => (
            <FilterChip key={m} active={marketFilter === m} onClick={() => setMarketFilter(m)}>{MARKET_LABEL[m]}</FilterChip>
          ))}
        </FilterRow>
        <div style={{ width: 1, height: 16, background: "var(--border-strong)" }} />
        <FilterRow label="标签">
          <FilterChip active={!tagFilter} onClick={() => setTagFilter(null)}>全部</FilterChip>
          {allTags.map(t => (
            <FilterChip key={t} active={tagFilter === t} onClick={() => setTagFilter(t)}>{t}</FilterChip>
          ))}
        </FilterRow>
      </div>

      {/* Table */}
      <div className="card">
        <div style={{ overflowX: "auto" }}>
        <table className="dtable">
          <thead>
            <tr>
              <SortHeader k="name">名称</SortHeader>
              <SortHeader k="symbol">代码</SortHeader>
              <SortHeader k="market">市场</SortHeader>
              <th>类型</th>
              <th>标签</th>
              <SortHeader k="quantity" align="right">持有量</SortHeader>
              <SortHeader k="costPrice" align="right">成本价</SortHeader>
              <SortHeader k="currentPrice" align="right">现价</SortHeader>
              <SortHeader k="daily" align="right">日涨跌</SortHeader>
              <SortHeader k="valueCny" align="right">市值 ¥</SortHeader>
              <SortHeader k="pnlCny" align="right">盈亏 ¥</SortHeader>
              <SortHeader k="pnlPct" align="right">盈亏 %</SortHeader>
              <th></th>
              <th style={{ textAlign: "center" }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(r => (
              <HoldingRow key={r.id} r={r} />
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </PageWrap>
  );
}

function HoldingRow({ r }) {
  const [hover, setHover] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showPrice, setShowPrice] = useState(false);
  const { navigate } = useRoute();

  return (
    <>
      <tr onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <span style={{ fontWeight: 500 }}>{r.name}</span>
        </td>
        <td><code style={{ fontSize: 11, color: "var(--fg-2)" }}>{r.symbol}</code></td>
        <td><span className="chip">{MARKET_LABEL[r.market]}</span></td>
        <td><span className="chip">{r.type}</span></td>
        <td>
          <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
            {r.tags.slice(0, 3).map(t => <span key={t} className="chip" style={{ background: "var(--bg-1)" }}>{t}</span>)}
          </div>
        </td>
        <td className="num">{fmt.qty(r.quantity)}</td>
        <td className="num"><span style={{ color: "var(--fg-2)" }}>{fmt.num(r.costPrice, 2)}</span></td>
        <td className="num">{fmt.num(r.currentPrice, 2)} <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{r.currency}</span></td>
        <td className="num" style={{ color: r.daily == null ? "var(--fg-3)" : r.daily >= 0 ? "var(--up)" : "var(--down)" }}>{r.daily == null ? "—" : fmt.pct(r.daily)}</td>
        <td className="num" style={{ fontWeight: 500 }}>{fmt.num(r.valueCny, 2)}</td>
        <td className="num" style={{ color: r.pnlCny >= 0 ? "var(--up)" : "var(--down)" }}>{fmt.signed(r.pnlCny, 2)}</td>
        <td className="num" style={{ color: r.pnlPct >= 0 ? "var(--up)" : "var(--down)", fontWeight: 500 }}>{fmt.pct(r.pnlPct)}</td>
        <td><Sparkline data={r.spark} width={50} height={18} /></td>
        <td style={{ textAlign: "center" }}>
          <div style={{ display: "inline-flex", gap: 3, opacity: hover ? 1 : 0.4, transition: "opacity var(--transition-fast)" }}>
            <button className="btn xs ghost" title="交易记录"
              onClick={() => navigate("transactions", { holdingId: r.id })}>交易</button>
            <button className="btn xs ghost" title="编辑"
              onClick={() => setShowEdit(true)}>编辑</button>
            <button className="btn xs ghost" title="设价"
              onClick={() => setShowPrice(true)}
              style={{ color: r.isManual ? "var(--up)" : undefined }}>设价</button>
          </div>
        </td>
      </tr>
      {showEdit && <EditHoldingModal r={r} onClose={() => setShowEdit(false)} />}
      {showPrice && <SetPriceModal r={r} onClose={() => setShowPrice(false)} />}
    </>
  );
}

function SummaryChip({ label, value, color, muted }) {
  return (
    <div style={{
      display: "inline-flex", flexDirection: "column", gap: 2,
      padding: "8px 14px",
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-2)",
    }}>
      <span className="mono" style={{ fontSize: 9, color: "var(--fg-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</span>
      <span className="num" style={{
        fontSize: "var(--fs-md)", fontWeight: 600,
        color: color === "up" ? "var(--up)" : color === "down" ? "var(--down)" : muted ? "var(--fg-2)" : "var(--fg)",
      }}>{value}</span>
    </div>
  );
}

function FilterRow({ label, children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginRight: 4 }}>{label}</span>
      {children}
    </div>
  );
}

function FilterChip({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        border: "1px solid " + (active ? "var(--fg)" : "var(--border)"),
        background: active ? "var(--fg)" : "var(--surface)",
        color: active ? "var(--bg)" : "var(--fg-1)",
        fontSize: 11,
        padding: "3px 9px",
        borderRadius: "var(--r-2)",
        cursor: "pointer",
        fontFamily: "inherit",
        transition: "all var(--transition-fast)",
      }}
    >
      {children}
    </button>
  );
}

// =============================================================
// Trends page
// =============================================================
function TrendsPage() {
  const [mode, setMode] = useState("total");
  const [holding, setHolding] = useState(HOLDINGS[0]?.symbol || "");
  const [tag, setTag] = useState(TAG_BUCKETS[0]?.tag || "");
  const [range, setRange] = useState("3M");
  const [chartData, setChartData] = useState([]);
  const [chartLoading, setChartLoading] = useState(false);

  const rangeMap = { "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "ALL": 9999 };
  const days = rangeMap[range];

  useEffect(() => {
    if (mode === "total") {
      setChartData(HISTORY.slice(-days));
      return;
    }
    if (mode === "holding" && !holding) return;
    if (mode === "tag" && !tag) return;

    setChartLoading(true);
    const url = mode === "holding"
      ? `/api/holding-value-history/${encodeURIComponent(holding)}`
      : `/api/tag-value-history/${encodeURIComponent(tag)}`;

    fetch(url)
      .then(r => r.json())
      .then(d => {
        const full = (d.dates || []).map((dt, i) => ({ date: dt, value: d.values[i] }));
        setChartData(full.slice(-days));
      })
      .catch(() => setChartData([]))
      .finally(() => setChartLoading(false));
  }, [mode, holding, tag, days]);

  const data = chartData;

  const startVal = data[0]?.value ?? 0;
  const endVal = data[data.length - 1]?.value ?? 0;
  const change = endVal - startVal;
  const changePct = startVal > 0 ? (change / startVal) * 100 : 0;
  const high = data.length ? Math.max(...data.map(d => d.value)) : 0;
  const low  = data.length ? Math.min(...data.map(d => d.value)) : 0;

  return (
    <PageWrap max={1400}>
      <div style={{ marginBottom: 16, display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "var(--fs-xl)", fontWeight: 600 }}>趋势分析</h2>
          <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em", marginTop: 2 }}>HISTORICAL VALUE TIMESERIES</div>
        </div>
        <RangeTabs value={range} onChange={setRange} />
      </div>

      {/* Mode switcher */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ display: "flex", padding: 3, background: "var(--bg-1)", borderRadius: "var(--r-2)", gap: 2 }}>
          {[
            { id: "total", label: "总资产" },
            { id: "holding", label: "按持仓" },
            { id: "tag", label: "按标签" },
          ].map(o => (
            <button
              key={o.id}
              onClick={() => setMode(o.id)}
              style={{
                border: 0, padding: "5px 12px", borderRadius: "var(--r-1)",
                fontSize: "var(--fs-xs)", fontFamily: "inherit",
                background: mode === o.id ? "var(--surface)" : "transparent",
                color: mode === o.id ? "var(--fg)" : "var(--fg-2)",
                fontWeight: mode === o.id ? 500 : 400,
                cursor: "pointer",
                boxShadow: mode === o.id ? "var(--shadow-1)" : "none",
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
        {mode === "holding" && (
          <select className="select" value={holding} onChange={e => setHolding(e.target.value)} style={{ minWidth: 280 }}>
            {HOLDINGS.map(h => <option key={h.symbol} value={h.symbol}>{h.name} ({h.symbol})</option>)}
          </select>
        )}
        {mode === "tag" && (
          <select className="select" value={tag} onChange={e => setTag(e.target.value)} style={{ minWidth: 200 }}>
            {TAG_BUCKETS.map(t => <option key={t.tag} value={t.tag}>{t.tag} · {t.value > 1e4 ? (t.value/1e4).toFixed(1)+"万" : t.value.toFixed(0)}</option>)}
          </select>
        )}
      </div>

      {/* Stats strip */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
        background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--r-3)",
        marginBottom: 14, overflow: "hidden",
      }}>
        <BMetric label="区间起始" value={fmt.cny(startVal, 0)} />
        <BMetric label="区间末值" value={fmt.cny(endVal, 0)} />
        <BMetric label="区间盈亏" value={fmt.signed(change, 0)} sub={fmt.pct(changePct)} color={change >= 0 ? "up" : "down"} />
        <BMetric label="区间峰值" value={fmt.cny(high, 0)} />
        <BMetric label="区间谷值" value={fmt.cny(low, 0)} />
      </div>

      {/* Chart */}
      <div className="card">
        <div className="card-head">
          <span className="title">
            <span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>SERIES</span>
            <span style={{ marginLeft: 8 }}>
              {mode === "total" ? "组合总资产" : mode === "holding" ? (HOLDINGS.find(h => h.symbol === holding)?.name || holding) : tag + " 标签"}
            </span>
          </span>
          <span className="mono" style={{ fontSize: 10, color: "var(--fg-3)" }}>{data.length} POINTS</span>
        </div>
        <div style={{ padding: "12px 16px 16px" }}>
          <LineChart
            data={data}
            height={360}
            accent={change >= 0 ? "var(--up)" : "var(--down)"}
            markers={
              mode === "total" ? PORTFOLIO_TRANSACTIONS
              : mode === "holding" ? PORTFOLIO_TRANSACTIONS.filter(t => t.symbol === holding)
              : mode === "tag" ? (() => {
                  const symbolsInTag = new Set(HOLDINGS.filter(h => h.tags.includes(tag)).map(h => h.symbol));
                  return PORTFOLIO_TRANSACTIONS.filter(t => symbolsInTag.has(t.symbol));
                })()
              : null
            }
          />
        </div>
      </div>

      {/* Backfill panel */}
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ display: "flex", alignItems: "center", padding: "16px 20px", gap: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 500 }}>回填历史数据</div>
            <div style={{ fontSize: "var(--fs-xs)", color: "var(--fg-2)", marginTop: 2 }}>
              根据已有的价格历史和交易记录，重建各日期的市值快照。
            </div>
          </div>
          <BackfillButton />
        </div>
      </div>
    </PageWrap>
  );
}

// Updated RangeTabs supporting controlled value
function RangeTabs({ value, onChange, options = ["1M","3M","6M","1Y","ALL"] }) {
  const [internal, setInternal] = useState(value || "3M");
  const v = value !== undefined ? value : internal;
  const set = onChange || setInternal;
  return (
    <div style={{ display: "flex", gap: 2, padding: 2, background: "var(--bg-1)", borderRadius: "var(--r-2)" }}>
      {options.map(o => (
        <button
          key={o}
          onClick={() => set(o)}
          style={{
            border: 0, padding: "3px 9px", borderRadius: "var(--r-1)",
            fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: "0.04em",
            background: v === o ? "var(--surface)" : "transparent",
            color: v === o ? "var(--fg)" : "var(--fg-3)",
            boxShadow: v === o ? "var(--shadow-1)" : "none",
            cursor: "pointer",
            transition: "all var(--transition-fast)",
          }}
        >{o}</button>
      ))}
    </div>
  );
}
window.RangeTabs = RangeTabs;

// =============================================================
// Transactions page
// =============================================================
function TransactionsPage({ params }) {
  const initId = params?.holdingId ?? HOLDINGS[0]?.id ?? null;
  const [holdingId, setHoldingId] = useState(initId);
  const [transactions, setTransactions] = useState([]);
  const [txLoading, setTxLoading] = useState(false);
  const h = HOLDINGS.find(x => x.id === holdingId);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    if (!holdingId) return;
    setTxLoading(true);
    fetch(`/api/transactions?holding_id=${holdingId}`)
      .then(r => r.json())
      .then(data => setTransactions(data))
      .catch(() => setTransactions([]))
      .finally(() => setTxLoading(false));
  }, [holdingId]);

  return (
    <PageWrap max={1100}>
      <div style={{ marginBottom: 16, display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "var(--fs-xl)", fontWeight: 600 }}>交易记录</h2>
          <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em", marginTop: 2 }}>TRANSACTION LEDGER</div>
        </div>
        <button className="btn primary sm" onClick={() => setShowAdd(true)}>+ 新增交易</button>
      </div>

      <div style={{ display: "flex", gap: 14, marginBottom: 14 }}>
        <select className="select" value={holdingId} onChange={e => setHoldingId(Number(e.target.value))} style={{ minWidth: 320 }}>
          {HOLDINGS.map(x => <option key={x.id} value={x.id}>{x.name} ({x.symbol})</option>)}
        </select>
      </div>

      {/* Holding summary */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
        background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--r-3)",
        marginBottom: 14, overflow: "hidden",
      }}>
        <BMetric label="标的" value={h.symbol} sub={h.name.length > 16 ? h.name.slice(0, 16) + "…" : h.name} />
        <BMetric label="持有量" value={fmt.qty(h.quantity)} />
        <BMetric label="均成本" value={fmt.num(h.costPrice, 2) + " " + h.currency} />
        <BMetric label="现价" value={fmt.num(h.currentPrice, 2) + " " + h.currency} sub={fmt.pct(h.daily)} color={h.daily >= 0 ? "up" : "down"} />
        <BMetric label="盈亏" value={fmt.signed(h.pnlCny, 0)} sub={fmt.pct(h.pnlPct)} color={h.pnlPct >= 0 ? "up" : "down"} />
      </div>

      {/* Transaction table */}
      <div className="card">
        <div className="card-head">
          <span className="title"><span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>LEDGER</span> <span style={{ marginLeft: 8 }}>{transactions.length} 笔</span></span>
        </div>
        <table className="dtable">
          <thead>
            <tr>
              <th>日期</th><th>类型</th>
              <th className="num">数量</th>
              <th className="num">价格</th>
              <th className="num">小计</th>
              <th>备注</th>
              <th style={{ textAlign: "center" }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {txLoading && (
              <tr><td colSpan={7} style={{ textAlign: "center", padding: 16, color: "var(--fg-3)" }}>加载中…</td></tr>
            )}
            {!txLoading && transactions.map(t => {
              const typeZh = TX_TYPE_ZH[t.type] || t.type;
              const isBuy = t.type === "BUY" || t.type === "TRANSFER_IN";
              return (
                <tr key={t.id}>
                  <td className="mono" style={{ fontSize: 11 }}>{t.date}</td>
                  <td>
                    <span className="chip" style={{ background: isBuy ? "var(--down-faint)" : "var(--up-faint)", color: isBuy ? "var(--down)" : "var(--up)" }}>
                      {typeZh}
                    </span>
                  </td>
                  <td className="num">{fmt.qty(t.quantity)}</td>
                  <td className="num">{fmt.num(t.unitPrice, 2)} <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{h?.currency || ""}</span></td>
                  <td className="num" style={{ fontWeight: 500 }}>{fmt.num(t.quantity * t.unitPrice, 2)}</td>
                  <td style={{ color: "var(--fg-2)" }}>{t.notes || "—"}</td>
                  <td style={{ textAlign: "center" }}>
                    <button className="btn xs ghost" style={{ color: "var(--down)" }}>删除</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showAdd && h && (
        <AddTransactionModal
          onClose={() => setShowAdd(false)}
          holdingId={holdingId}
          symbol={h.symbol}
          currency={h.currency}
          onSaved={() => {
            fetch(`/api/transactions?holding_id=${holdingId}`)
              .then(r => r.json()).then(setTransactions);
          }}
        />
      )}
    </PageWrap>
  );
}

function AddTransactionModal({ onClose, holdingId, symbol, currency, onSaved }) {
  const today = new Date().toISOString().slice(0, 10);
  const [txType, setTxType] = useState("BUY");
  const [date, setDate] = useState(today);
  const [quantity, setQuantity] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!quantity || !unitPrice) { alert("请填写数量和价格"); return; }
    setSaving(true);
    try {
      const r = await fetch(`/api/holdings/${holdingId}/transactions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: txType, date, quantity: +quantity, unitPrice: +unitPrice, notes }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "保存失败");
      onSaved?.();
      onClose();
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="新增交易" onClose={onClose} width={420}>
      <div style={{ display: "grid", gap: 14 }}>
        <Field label="标的"><div className="mono" style={{ fontSize: 12 }}>{symbol}</div></Field>
        <Field label="类型">
          <div style={{ display: "flex", gap: 6 }}>
            {[["BUY","买入"],["SELL","卖出"]].map(([val, label]) => (
              <button key={val} className="btn sm"
                style={{ flex: 1, background: txType === val ? (val==="BUY"?"var(--down-faint)":"var(--up-faint)") : undefined,
                         color: txType === val ? (val==="BUY"?"var(--down)":"var(--up)") : undefined,
                         borderColor: txType === val ? "transparent" : undefined }}
                onClick={() => setTxType(val)}>{label}</button>
            ))}
          </div>
        </Field>
        <Field label="日期"><input className="input" type="date" value={date} onChange={e => setDate(e.target.value)} /></Field>
        <Field label="数量"><input className="input" type="number" placeholder="0" value={quantity} onChange={e => setQuantity(e.target.value)} /></Field>
        <Field label={`价格 (${currency})`}><input className="input" type="number" step="0.01" placeholder="0.00" value={unitPrice} onChange={e => setUnitPrice(e.target.value)} /></Field>
        <Field label="备注 (可选)"><input className="input" placeholder="" value={notes} onChange={e => setNotes(e.target.value)} /></Field>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button className="btn sm" onClick={onClose}>取消</button>
          <button className="btn primary sm" onClick={handleSave} disabled={saving}>{saving ? "保存中…" : "保存"}</button>
        </div>
      </div>
    </Modal>
  );
}

function BackfillButton() {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(null);
  const handleClick = async () => {
    setLoading(true); setDone(null);
    try {
      const r = await fetch("/api/backfill-value-history", { method: "POST" });
      const d = await r.json();
      setDone(d.days_processed);
      window.dispatchEvent(new Event("portfolio-refreshed"));
    } catch (e) {
      alert("回填失败: " + e);
    } finally { setLoading(false); }
  };
  return (
    <button className="btn sm" onClick={handleClick} disabled={loading}>
      {loading ? "回填中…" : done != null ? `已回填 ${done} 天` : "回填历史"}
    </button>
  );
}

// =============================================================
// Add holding form
// =============================================================
function AddHoldingPage() {
  const { navigate } = useRoute?.() || {};
  const [form, setForm] = useState({
    symbol: "", market: "CN", name: "", asset_type: "stock",
    currency: "CNY", quantity: "", cost_price: "", tags: "", notes: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const MARKET_CURRENCY = { CN: "CNY", US: "USD", JP: "JPY", CRYPTO: "USD", OTHER: "CNY" };

  const handleSubmit = async () => {
    if (!form.symbol || !form.quantity || !form.cost_price) { alert("请填写代码、数量和成本价"); return; }
    setSaving(true);
    try {
      const r = await fetch("/api/holdings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form, quantity: +form.quantity, cost_price: +form.cost_price,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || "保存失败");
      window.dispatchEvent(new Event("portfolio-refreshed"));
      navigate?.("holdings");
    } catch (e) {
      alert(e.message);
    } finally { setSaving(false); }
  };

  return (
    <PageWrap max={680}>
      <div style={{ marginBottom: 18 }}>
        <h2 style={{ margin: 0, fontSize: "var(--fs-xl)", fontWeight: 600 }}>添加持仓</h2>
        <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em", marginTop: 2 }}>NEW POSITION</div>
      </div>
      <div className="card" style={{ padding: 24 }}>
        <div style={{ display: "grid", gap: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <Field label="标的代码" hint="A股 600519.SH · 美股 AAPL · 日股 7203.T">
              <input className="input" placeholder="例如 AAPL" value={form.symbol}
                onChange={e => set("symbol", e.target.value.toUpperCase())} />
            </Field>
            <Field label="市场">
              <select className="select" value={form.market} onChange={e => {
                const m = e.target.value;
                set("market", m);
                set("currency", MARKET_CURRENCY[m] || "CNY");
              }}>
                <option value="CN">A股 (CN)</option>
                <option value="US">美股 (US)</option>
                <option value="JP">日股 (JP)</option>
                <option value="CRYPTO">加密货币</option>
                <option value="OTHER">其他</option>
              </select>
            </Field>
          </div>
          <Field label="名称" hint="留空将自动从行情数据获取">
            <input className="input" placeholder="（可自动填充）" value={form.name} onChange={e => set("name", e.target.value)} />
          </Field>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
            <Field label="资产类型">
              <select className="select" value={form.asset_type} onChange={e => set("asset_type", e.target.value)}>
                <option value="stock">股票</option>
                <option value="fund">基金</option>
                <option value="etf">ETF</option>
                <option value="bond">债券</option>
                <option value="crypto">加密</option>
                <option value="other">其他</option>
              </select>
            </Field>
            <Field label="持有数量">
              <input className="input" type="number" placeholder="0.0000" step="0.0001" value={form.quantity}
                onChange={e => set("quantity", e.target.value)} />
            </Field>
            <Field label="成本价">
              <input className="input" type="number" placeholder="0.00" step="0.01" value={form.cost_price}
                onChange={e => set("cost_price", e.target.value)} />
            </Field>
          </div>
          <Field label="标签" hint="用逗号分隔，例如 长期持有, 科技, 美股">
            <input className="input" placeholder="" value={form.tags} onChange={e => set("tags", e.target.value)} />
          </Field>
          <Field label="备注 (可选)">
            <textarea className="input" rows={3} style={{ height: "auto", padding: 10, resize: "vertical" }}
              value={form.notes} onChange={e => set("notes", e.target.value)} />
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8, paddingTop: 16, borderTop: "1px solid var(--border-subtle)" }}>
            <button className="btn" onClick={() => navigate?.("holdings")}>取消</button>
            <button className="btn primary" onClick={handleSubmit} disabled={saving}>{saving ? "保存中…" : "保存持仓"}</button>
          </div>
        </div>
      </div>
    </PageWrap>
  );
}

function Field({ label, hint, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: "var(--fs-xs)", fontWeight: 500, color: "var(--fg-1)" }}>{label}</span>
      {children}
      {hint && <span style={{ fontSize: "var(--fs-xxs)", color: "var(--fg-3)" }}>{hint}</span>}
    </label>
  );
}

// =============================================================
// Login page (full-screen, separate from main layout)
// =============================================================
function LoginPage({ onLogin }) {
  const [token, setToken] = useState("");
  return (
    <div style={{
      minHeight: "100vh",
      background: "var(--bg)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 20,
    }}>
      <div style={{ width: 380 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28, justifyContent: "center" }}>
          <BrandMark />
          <span style={{ fontWeight: 600, fontSize: "var(--fs-md)" }}>持仓追踪</span>
        </div>
        <div className="card" style={{ padding: 28 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: "var(--fs-lg)", fontWeight: 600 }}>登录</h3>
          <p style={{ margin: "0 0 20px", color: "var(--fg-2)", fontSize: "var(--fs-sm)" }}>
            输入访问 Token 以继续
          </p>
          <div style={{ display: "grid", gap: 12 }}>
            <Field label="访问 Token">
              <input className="input" type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="••••••••" autoFocus />
            </Field>
            <button className="btn primary" style={{ height: 36, justifyContent: "center" }} onClick={onLogin}>登录</button>
          </div>
          <div className="mono" style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border-subtle)", fontSize: 10, color: "var(--fg-3)", lineHeight: 1.6 }}>
            <div>API · <span style={{ color: "var(--fg-2)" }}>Authorization: Bearer ...</span></div>
            <div>MCP · <span style={{ color: "var(--fg-2)" }}>POST /mcp endpoint</span></div>
          </div>
        </div>
        <div className="mono" style={{ textAlign: "center", marginTop: 18, fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em" }}>
          PORTFOLIO TRACKER · v2.4
        </div>
      </div>
    </div>
  );
}

// =============================================================
// Modal primitive
// =============================================================
function Modal({ title, children, onClose, width = 480 }) {
  useEffect(() => {
    const onEsc = e => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose]);
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.32)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 200,
      animation: "fadeIn 160ms ease-out",
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width, maxWidth: "92vw",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-4)",
        boxShadow: "var(--shadow-3)",
        animation: "modalIn 200ms cubic-bezier(0.2,0,0,1)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid var(--border-subtle)" }}>
          <h4 style={{ margin: 0, fontSize: "var(--fs-md)", fontWeight: 600 }}>{title}</h4>
          <button className="btn xs ghost" onClick={onClose} style={{ fontSize: 14 }}>×</button>
        </div>
        <div style={{ padding: 18 }}>{children}</div>
      </div>
    </div>
  );
}

// =============================================================
// Edit holding modal
// =============================================================
function EditHoldingModal({ r, onClose }) {
  const [name, setName] = useState(r.name);
  const [tags, setTags] = useState((r.tags || []).join(", "));
  const [notes, setNotes] = useState(r.notes || "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`/api/holdings/${r.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, tags, notes }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "保存失败");
      window.dispatchEvent(new Event("portfolio-refreshed"));
      onClose();
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`编辑持仓 · ${r.symbol}`} onClose={onClose} width={440}>
      <div style={{ display: "grid", gap: 14 }}>
        <Field label="名称">
          <input className="input" value={name} onChange={e => setName(e.target.value)} />
        </Field>
        <Field label="标签" hint="用逗号分隔">
          <input className="input" value={tags} onChange={e => setTags(e.target.value)} placeholder="科技, 长期持有" />
        </Field>
        <Field label="备注">
          <textarea className="input" rows={3} style={{ height: "auto", padding: 10, resize: "vertical" }}
            value={notes} onChange={e => setNotes(e.target.value)} />
        </Field>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button className="btn sm" onClick={onClose}>取消</button>
          <button className="btn primary sm" onClick={handleSave} disabled={saving}>
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// =============================================================
// Set price override modal
// =============================================================
function SetPriceModal({ r, onClose }) {
  const [price, setPrice] = useState(r.currentPrice != null ? String(r.currentPrice) : "");
  const [saving, setSaving] = useState(false);

  const handleSet = async () => {
    if (!price || isNaN(+price) || +price <= 0) { alert("请输入有效价格"); return; }
    setSaving(true);
    try {
      const res = await fetch("/api/override-price", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: r.symbol, price: +price, currency: r.currency }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "设价失败");
      window.dispatchEvent(new Event("portfolio-refreshed"));
      onClose();
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setSaving(true);
    try {
      await fetch("/api/clear-override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: r.symbol }),
      });
      window.dispatchEvent(new Event("portfolio-refreshed"));
      onClose();
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`手动设价 · ${r.symbol}`} onClose={onClose} width={380}>
      <div style={{ display: "grid", gap: 14 }}>
        {r.isManual && (
          <div style={{ fontSize: "var(--fs-xs)", color: "var(--up)", padding: "6px 10px",
            background: "var(--up-faint)", borderRadius: "var(--r-2)" }}>
            当前为手动价格
          </div>
        )}
        <Field label={`价格 (${r.currency})`}>
          <input className="input" type="number" step="0.0001" value={price}
            onChange={e => setPrice(e.target.value)} autoFocus />
        </Field>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginTop: 4 }}>
          {r.isManual ? (
            <button className="btn sm" style={{ color: "var(--down)" }}
              onClick={handleClear} disabled={saving}>清除手动设价</button>
          ) : <span />}
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn sm" onClick={onClose}>取消</button>
            <button className="btn primary sm" onClick={handleSet} disabled={saving}>
              {saving ? "设置中…" : "确认设价"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

Object.assign(window, { HoldingsPage, TrendsPage, TransactionsPage, AddHoldingPage, LoginPage, Modal, Field });
