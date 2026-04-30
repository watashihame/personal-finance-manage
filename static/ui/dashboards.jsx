/* global React */
// Three dashboard variants: A (conservative), B (standard terminal), C (bold dense).

const { useState, useEffect } = React;

// =============================================================
// Shared dashboard pieces
// =============================================================

function MetricCard({ label, value, sub, accent, mono = true, big = false }) {
  return (
    <div style={{
      padding: "16px 18px",
      background: "var(--surface)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-3)",
      display: "flex", flexDirection: "column", gap: 6,
      minWidth: 0,
    }}>
      <div style={{ fontSize: "var(--fs-xxs)", color: "var(--fg-3)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
      <div className={mono ? "num" : ""} style={{
        fontSize: big ? "var(--fs-3xl)" : "var(--fs-2xl)",
        fontWeight: 600,
        color: accent || "var(--fg)",
        lineHeight: 1.1,
        letterSpacing: "-0.02em",
      }}>{value}</div>
      {sub && <div style={{ fontSize: "var(--fs-xs)", color: "var(--fg-2)" }}>{sub}</div>}
    </div>
  );
}

function PageWrap({ children, max = 1400 }) {
  return (
    <div className="page-enter" style={{ maxWidth: max, margin: "0 auto", padding: "24px 24px 32px" }}>
      {children}
    </div>
  );
}

function SectionTitle({ children, action, sub }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h3 style={{ margin: 0, fontSize: "var(--fs-md)", fontWeight: 600, letterSpacing: "-0.005em" }}>{children}</h3>
        {sub && <span style={{ color: "var(--fg-3)", fontSize: "var(--fs-xs)" }}>{sub}</span>}
      </div>
      {action}
    </div>
  );
}

// =============================================================
// VARIANT A — Conservative. Spacious, hero NAV chart, calm cards.
// =============================================================
function DashboardA() {
  const dayUp = DAY_PNL >= 0;
  const totalUp = TOTAL_PNL >= 0;

  const palette = ["var(--cat-1)", "var(--cat-2)", "var(--cat-3)", "var(--cat-4)", "var(--cat-5)", "var(--cat-6)", "var(--cat-7)", "var(--cat-8)"];

  // top distribution: top 8 by value, rest as "其他"
  const sorted = [...HOLDINGS].sort((a, b) => b.valueCny - a.valueCny);
  const top = sorted.slice(0, 7).map(h => ({ label: h.name, value: h.valueCny }));
  const rest = sorted.slice(7).reduce((s, h) => s + h.valueCny, 0);
  if (rest > 0) top.push({ label: "其他持仓", value: rest });

  return (
    <PageWrap max={1280}>
      {/* Hero block */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 18 }}>
        <div style={{
          padding: "28px 32px",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-4)",
          display: "flex", flexDirection: "column", gap: 18,
        }}>
          <div>
            <div style={{ fontSize: "var(--fs-xs)", color: "var(--fg-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
              总资产 · 人民币
            </div>
            <div className="num" style={{ fontSize: "var(--fs-4xl)", fontWeight: 600, lineHeight: 1, letterSpacing: "-0.03em" }}>
              {fmt.cny(TOTAL_VALUE, 2)}
            </div>
          </div>
          <div style={{ display: "flex", gap: 24 }}>
            <div>
              <div style={{ fontSize: "var(--fs-xxs)", color: "var(--fg-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>今日</div>
              <div className="num" style={{ fontSize: "var(--fs-lg)", fontWeight: 500, color: dayUp ? "var(--up)" : "var(--down)" }}>
                {fmt.signed(DAY_PNL, 2)} <span style={{ fontSize: "var(--fs-sm)", marginLeft: 6 }}>{fmt.pct(DAY_PNL_PCT)}</span>
              </div>
            </div>
            <div style={{ width: 1, background: "var(--border)" }} />
            <div>
              <div style={{ fontSize: "var(--fs-xxs)", color: "var(--fg-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>累计</div>
              <div className="num" style={{ fontSize: "var(--fs-lg)", fontWeight: 500, color: totalUp ? "var(--up)" : "var(--down)" }}>
                {fmt.signed(TOTAL_PNL, 2)} <span style={{ fontSize: "var(--fs-sm)", marginLeft: 6 }}>{fmt.pct(TOTAL_PNL_PCT)}</span>
              </div>
            </div>
            <div style={{ width: 1, background: "var(--border)" }} />
            <div>
              <div style={{ fontSize: "var(--fs-xxs)", color: "var(--fg-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>成本</div>
              <div className="num" style={{ fontSize: "var(--fs-lg)", fontWeight: 500, color: "var(--fg-1)" }}>{fmt.cny(TOTAL_COST, 0)}</div>
            </div>
          </div>
        </div>

        <div style={{
          padding: "20px 24px 16px",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-4)",
          display: "flex", flexDirection: "column",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
            <div style={{ fontSize: "var(--fs-sm)", fontWeight: 600 }}>净值走势</div>
            <RangeTabs />
          </div>
          <div style={{ flex: 1, minHeight: 160 }}>
            <LineChart data={HISTORY.slice(-90)} height={170} markers={PORTFOLIO_TRANSACTIONS} />
          </div>
        </div>
      </div>

      {/* Distribution + watchlist */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.2fr)", gap: 18, marginBottom: 18 }}>
        <div className="card">
          <div className="card-head">
            <span className="title">资产分配</span>
            <span style={{ color: "var(--fg-3)", fontSize: "var(--fs-xs)" }}>{HOLDINGS.length} 项持仓</span>
          </div>
          <div className="card-body" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 28, alignItems: "center" }}>
            <DonutChart data={top} size={180} thickness={20} palette={palette} />
            <BarList data={top.slice(0, 6)} palette={palette} valueFormat={v => fmt.k(v)} labelMax={14} />
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="title">值得关注</span>
            <div style={{ display: "flex", gap: 4 }}>
              <span className="chip up">{TOP_GAINERS.length} 上涨</span>
              <span className="chip down">{TOP_LOSERS.length} 下跌</span>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
            <WatchColumn title="盈利领先" rows={TOP_GAINERS} />
            <WatchColumn title="亏损警示" rows={TOP_LOSERS} divider />
          </div>
        </div>
      </div>

      {/* Holdings preview */}
      <HoldingsPreviewTable />
    </PageWrap>
  );
}

function RangeTabs({ value = "3M", options = ["1M","3M","6M","1Y","ALL"] }) {
  const [v, setV] = useState(value);
  return (
    <div style={{ display: "flex", gap: 2, padding: 2, background: "var(--bg-1)", borderRadius: "var(--r-2)" }}>
      {options.map(o => (
        <button
          key={o}
          onClick={() => setV(o)}
          className="mono"
          style={{
            border: 0, padding: "3px 8px", borderRadius: "var(--r-1)",
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

function WatchColumn({ title, rows, divider }) {
  return (
    <div style={{ padding: "12px 16px", borderLeft: divider ? "1px solid var(--border-subtle)" : "none" }}>
      <div style={{ fontSize: "var(--fs-xxs)", color: "var(--fg-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.map(r => (
          <div key={r.id} style={{
            display: "grid", gridTemplateColumns: "1fr auto auto", gap: 12,
            alignItems: "center", padding: "8px 0",
            borderBottom: "1px dashed var(--border-subtle)",
          }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: "var(--fs-sm)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.name}
              </div>
              <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)" }}>{r.symbol}</div>
            </div>
            <Sparkline data={r.spark} width={56} height={20} />
            <div className="num" style={{ fontSize: "var(--fs-sm)", color: r.pnlPct >= 0 ? "var(--up)" : "var(--down)", textAlign: "right", minWidth: 60 }}>
              {fmt.pct(r.pnlPct)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HoldingsPreviewTable() {
  const rows = [...HOLDINGS].sort((a, b) => b.valueCny - a.valueCny).slice(0, 8);
  return (
    <div className="card">
      <div className="card-head">
        <span className="title">持仓概览 <span style={{ color: "var(--fg-3)", fontWeight: 400, marginLeft: 6 }}>前 8 项</span></span>
        <button className="btn sm ghost">查看全部 {HOLDINGS.length} 项 →</button>
      </div>
      <table className="dtable">
        <thead>
          <tr>
            <th>名称</th><th>代码</th><th>市场</th>
            <th>标签</th>
            <th className="num">持有量</th>
            <th className="num">现价</th>
            <th className="num">市值 (¥)</th>
            <th className="num">日涨跌</th>
            <th className="num">盈亏 %</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id}>
              <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</td>
              <td><code style={{ fontSize: 11, color: "var(--fg-2)" }}>{r.symbol}</code></td>
              <td><span className="chip">{MARKET_LABEL[r.market]}</span></td>
              <td>
                <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                  {(r.tags || []).slice(0, 2).map(t => (
                    <span key={t} className="chip" style={{ background: "var(--bg-1)" }}>{t}</span>
                  ))}
                </div>
              </td>
              <td className="num">{fmt.qty(r.quantity)}</td>
              <td className="num">{fmt.num(r.currentPrice, 2)} <span style={{ color: "var(--fg-3)", fontSize: 10 }}>{r.currency}</span></td>
              <td className="num" style={{ fontWeight: 500 }}>{fmt.num(r.valueCny, 2)}</td>
              <td className="num" style={{ color: r.daily == null ? "var(--fg-3)" : r.daily >= 0 ? "var(--up)" : "var(--down)" }}>
                {r.daily == null ? "—" : fmt.pct(r.daily)}
              </td>
              <td className="num" style={{ color: r.pnlPct >= 0 ? "var(--up)" : "var(--down)" }}>{fmt.pct(r.pnlPct)}</td>
              <td><Sparkline data={r.spark} width={50} height={18} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// =============================================================
// VARIANT B — Standard terminal. Tighter, monospace headers, grid lines.
// =============================================================
function DashboardB() {
  const dayUp = DAY_PNL >= 0;
  const totalUp = TOTAL_PNL >= 0;
  const palette = ["var(--cat-1)", "var(--cat-2)", "var(--cat-3)", "var(--cat-4)", "var(--cat-5)", "var(--cat-6)", "var(--cat-7)", "var(--cat-8)"];
  const sorted = [...HOLDINGS].sort((a, b) => b.valueCny - a.valueCny);
  const top = sorted.slice(0, 8).map(h => ({ label: h.name, value: h.valueCny }));

  return (
    <div className="page-enter" style={{ padding: "16px 20px 24px" }}>
      {/* Top metrics strip */}
      <div style={{
        display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr 1fr",
        border: "1px solid var(--border)",
        background: "var(--surface)",
        borderRadius: "var(--r-3)",
        marginBottom: 14,
        overflow: "hidden",
      }}>
        <BMetric label="总资产 · CNY" value={fmt.cny(TOTAL_VALUE, 2)} hero />
        <BMetric label="今日盈亏" value={fmt.signed(DAY_PNL, 2)} sub={fmt.pct(DAY_PNL_PCT)} color={dayUp ? "up" : "down"} />
        <BMetric label="累计盈亏" value={fmt.signed(TOTAL_PNL, 2)} sub={fmt.pct(TOTAL_PNL_PCT)} color={totalUp ? "up" : "down"} />
        <BMetric label="总成本" value={fmt.cny(TOTAL_COST, 0)} sub={`${HOLDINGS.length} 项持仓`} />
        <BMetric label="日波幅" value={(Math.abs(DAY_PNL_PCT) * 1.6).toFixed(2) + "%"} sub="60D vol" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 14, marginBottom: 14 }}>
        {/* NAV chart */}
        <div className="card">
          <div className="card-head" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <span className="title">
              <span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>NAV</span>
              <span style={{ marginLeft: 8 }}>组合净值</span>
            </span>
            <RangeTabs />
          </div>
          <div style={{ padding: "8px 12px 12px" }}>
            <LineChart data={HISTORY.slice(-90)} height={220} markers={PORTFOLIO_TRANSACTIONS} />
          </div>
        </div>

        {/* Allocation */}
        <div className="card">
          <div className="card-head">
            <span className="title">
              <span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>ALLOC</span>
              <span style={{ marginLeft: 8 }}>分布</span>
            </span>
          </div>
          <div className="card-body" style={{ display: "flex", justifyContent: "center", padding: "8px 14px 14px" }}>
            <DonutChart data={top} size={200} thickness={22} palette={palette} />
          </div>
        </div>
      </div>

      {/* Watchlist + tags */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginBottom: 14 }}>
        <div className="card">
          <div className="card-head"><span className="title"><span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>GAINERS</span><span style={{ marginLeft: 8 }}>盈利领先</span></span></div>
          <BList rows={TOP_GAINERS} />
        </div>
        <div className="card">
          <div className="card-head"><span className="title"><span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>LOSERS</span><span style={{ marginLeft: 8 }}>亏损警示</span></span></div>
          <BList rows={TOP_LOSERS} />
        </div>
        <div className="card">
          <div className="card-head"><span className="title"><span className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.1em" }}>TAGS</span><span style={{ marginLeft: 8 }}>标签</span></span></div>
          <div style={{ padding: "10px 14px 14px" }}>
            <BarList data={TAG_BUCKETS.slice(0, 7).map(t => ({ label: t.tag, value: t.value }))} palette={palette} valueFormat={v => fmt.k(v)} />
          </div>
        </div>
      </div>

      {/* Holdings table */}
      <HoldingsPreviewTable />
    </div>
  );
}

function BMetric({ label, value, sub, color, hero }) {
  return (
    <div style={{
      padding: hero ? "16px 20px" : "16px 18px",
      borderRight: "1px solid var(--border-subtle)",
    }}>
      <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>
        {label}
      </div>
      <div className="num" style={{
        fontSize: hero ? "var(--fs-2xl)" : "var(--fs-xl)",
        fontWeight: 600,
        letterSpacing: "-0.02em",
        color: color === "up" ? "var(--up)" : color === "down" ? "var(--down)" : "var(--fg)",
        lineHeight: 1.1,
      }}>{value}</div>
      {sub && <div className="num" style={{ fontSize: 11, color: color ? (color === "up" ? "var(--up)" : "var(--down)") : "var(--fg-2)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function BList({ rows }) {
  return (
    <div style={{ padding: "6px 0" }}>
      {rows.map(r => (
        <div key={r.id} style={{
          display: "grid",
          gridTemplateColumns: "1fr auto auto",
          gap: 10, alignItems: "center",
          padding: "8px 14px",
          borderBottom: "1px solid var(--border-subtle)",
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: "var(--fs-sm)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</div>
            <div className="mono" style={{ fontSize: 10, color: "var(--fg-3)" }}>{r.symbol}</div>
          </div>
          <Sparkline data={r.spark} width={48} height={18} />
          <div className="num" style={{ color: r.pnlPct >= 0 ? "var(--up)" : "var(--down)", fontWeight: 500, minWidth: 56, textAlign: "right" }}>
            {fmt.pct(r.pnlPct)}
          </div>
        </div>
      ))}
    </div>
  );
}

// =============================================================
// VARIANT C — Bold dense (Bloomberg-feel). Mono-heavy, info-dense, two-column layout.
// =============================================================
function DashboardC() {
  const dayUp = DAY_PNL >= 0;
  const totalUp = TOTAL_PNL >= 0;
  const palette = ["var(--cat-1)", "var(--cat-2)", "var(--cat-3)", "var(--cat-4)", "var(--cat-5)", "var(--cat-6)", "var(--cat-7)", "var(--cat-8)"];

  return (
    <div className="page-enter" style={{ padding: "10px 14px 18px", fontFamily: "var(--font-ui)" }}>
      {/* Hero terminal block */}
      <div style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-2)",
        padding: "14px 18px",
        marginBottom: 10,
        display: "grid",
        gridTemplateColumns: "1.2fr 1fr 1fr 1fr 1fr",
        gap: 0,
      }}>
        <CHeroCell label="PORTFOLIO NAV / CNY" value={fmt.cny(TOTAL_VALUE, 2)} big />
        <CHeroCell label="DAY P&L" value={fmt.signed(DAY_PNL, 0)} sub={fmt.pct(DAY_PNL_PCT)} color={dayUp ? "up" : "down"} />
        <CHeroCell label="TOTAL P&L" value={fmt.signed(TOTAL_PNL, 0)} sub={fmt.pct(TOTAL_PNL_PCT)} color={totalUp ? "up" : "down"} />
        <CHeroCell label="COST BASIS" value={fmt.k(TOTAL_COST)} sub={`${HOLDINGS.length} POSITIONS`} />
        <CHeroCell label="DAY RANGE" value={(Math.abs(DAY_PNL_PCT) * 1.4).toFixed(2) + "%"} sub="60D σ" last />
      </div>

      {/* Main grid */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.5fr) minmax(0, 1fr)", gap: 10, marginBottom: 10 }}>
        {/* NAV + sub-charts */}
        <div style={{ display: "grid", gridTemplateRows: "auto auto", gap: 10 }}>
          <div className="card" style={{ borderRadius: "var(--r-2)" }}>
            <CHeader title="PORTFOLIO NAV" right={<RangeTabs />} />
            <div style={{ padding: "4px 10px 10px" }}>
              <LineChart data={HISTORY} height={240} markers={PORTFOLIO_TRANSACTIONS} />
            </div>
          </div>

          {/* Quad mini-charts */}
          <div className="card" style={{ borderRadius: "var(--r-2)" }}>
            <CHeader title="WATCH GRID" sub="6 active" />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", borderTop: "1px solid var(--border-subtle)" }}>
              {[...HOLDINGS].sort((a, b) => Math.abs(b.daily) - Math.abs(a.daily)).slice(0, 6).map((h, i) => (
                <div key={h.id} style={{
                  padding: "10px 12px",
                  borderRight: (i % 3 !== 2) ? "1px solid var(--border-subtle)" : "none",
                  borderBottom: i < 3 ? "1px solid var(--border-subtle)" : "none",
                  display: "flex", flexDirection: "column", gap: 4, minWidth: 0,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <code style={{ fontSize: 11, color: "var(--fg-1)", fontWeight: 600 }}>{h.symbol}</code>
                    <span className="num" style={{ fontSize: 11, color: h.daily >= 0 ? "var(--up)" : "var(--down)", fontWeight: 500 }}>{fmt.pct(h.daily)}</span>
                  </div>
                  <div style={{ fontSize: 10, color: "var(--fg-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</div>
                  <Sparkline data={h.spark} width={140} height={26} fill />
                  <div className="num" style={{ fontSize: 10, color: "var(--fg-2)", display: "flex", justifyContent: "space-between" }}>
                    <span>{fmt.num(h.currentPrice, 2)} {h.currency}</span>
                    <span style={{ color: h.pnlPct >= 0 ? "var(--up)" : "var(--down)" }}>{fmt.pct(h.pnlPct)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right column: distribution + tags + movers */}
        <div style={{ display: "grid", gridTemplateRows: "auto auto auto", gap: 10 }}>
          <div className="card" style={{ borderRadius: "var(--r-2)" }}>
            <CHeader title="ALLOCATION" sub={`${HOLDINGS.length} pos`} />
            <div style={{ padding: "8px 12px 12px" }}>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 10 }}>
                <DonutChart data={[...HOLDINGS].sort((a,b) => b.valueCny-a.valueCny).slice(0, 8).map(h => ({ label: h.name, value: h.valueCny }))} size={150} thickness={18} palette={palette} />
              </div>
              <BarList
                data={TAG_BUCKETS.slice(0, 6).map(t => ({ label: t.tag, value: t.value }))}
                palette={palette}
                valueFormat={v => fmt.k(v)}
                labelMax={10}
              />
            </div>
          </div>

          <div className="card" style={{ borderRadius: "var(--r-2)" }}>
            <CHeader title="MOVERS" sub="today" />
            <div style={{ padding: "4px 0" }}>
              {TOP_DAY.map(r => (
                <div key={r.id} style={{
                  display: "grid", gridTemplateColumns: "auto 1fr auto",
                  gap: 10, alignItems: "center",
                  padding: "6px 12px",
                  borderBottom: "1px solid var(--border-subtle)",
                }}>
                  <code style={{ fontSize: 10, color: "var(--fg-1)", minWidth: 70, fontWeight: 500 }}>{r.symbol}</code>
                  <Sparkline data={r.spark} width={80} height={18} />
                  <span className="num" style={{ fontSize: 11, color: r.daily >= 0 ? "var(--up)" : "var(--down)", fontWeight: 500, minWidth: 56, textAlign: "right" }}>{fmt.pct(r.daily)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Holdings dense table */}
      <div className="card" style={{ borderRadius: "var(--r-2)" }}>
        <CHeader title="HOLDINGS" sub={`${HOLDINGS.length} positions · sorted by market value`} />
        <table className="dtable" style={{ fontSize: "var(--fs-xs)" }}>
          <thead>
            <tr>
              <th>SYMBOL</th><th>NAME</th><th>MKT</th>
              <th className="num">QTY</th>
              <th className="num">PRICE</th>
              <th className="num">DAY%</th>
              <th className="num">VALUE ¥</th>
              <th className="num">P&L ¥</th>
              <th className="num">P&L%</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {[...HOLDINGS].sort((a,b)=>b.valueCny-a.valueCny).map(r => (
              <tr key={r.id}>
                <td><code style={{ fontSize: 11, color: "var(--fg-1)", fontWeight: 500 }}>{r.symbol}</code></td>
                <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</td>
                <td><span className="chip">{MARKET_LABEL[r.market]}</span></td>
                <td className="num">{fmt.qty(r.quantity)}</td>
                <td className="num">{fmt.num(r.currentPrice, 2)}</td>
                <td className="num" style={{ color: r.daily >= 0 ? "var(--up)" : "var(--down)", fontWeight: 500 }}>{fmt.pct(r.daily)}</td>
                <td className="num" style={{ fontWeight: 500 }}>{fmt.num(r.valueCny, 0)}</td>
                <td className="num" style={{ color: r.pnlCny >= 0 ? "var(--up)" : "var(--down)" }}>{fmt.signed(r.pnlCny, 0)}</td>
                <td className="num" style={{ color: r.pnlPct >= 0 ? "var(--up)" : "var(--down)", fontWeight: 500 }}>{fmt.pct(r.pnlPct)}</td>
                <td><Sparkline data={r.spark} width={56} height={16} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CHeroCell({ label, value, sub, color, big, last }) {
  return (
    <div style={{
      padding: big ? "0 24px 0 0" : "0 18px",
      borderRight: last ? "none" : "1px solid var(--border-subtle)",
      display: "flex", flexDirection: "column", justifyContent: "center", gap: 4,
    }}>
      <div className="mono" style={{ fontSize: 9, color: "var(--fg-3)", letterSpacing: "0.12em" }}>{label}</div>
      <div className="num" style={{
        fontSize: big ? "var(--fs-3xl)" : "var(--fs-xl)",
        fontWeight: 600,
        letterSpacing: "-0.02em",
        lineHeight: 1.1,
        color: color === "up" ? "var(--up)" : color === "down" ? "var(--down)" : "var(--fg)",
      }}>{value}</div>
      {sub && <div className="num" style={{ fontSize: 10, color: color === "up" ? "var(--up)" : color === "down" ? "var(--down)" : "var(--fg-2)" }}>{sub}</div>}
    </div>
  );
}

function CHeader({ title, sub, right }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "8px 12px",
      background: "var(--surface-2)",
      borderBottom: "1px solid var(--border-subtle)",
    }}>
      <div className="mono" style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--fg-1)", fontWeight: 600 }}>
        {title} {sub && <span style={{ color: "var(--fg-3)", fontWeight: 400, marginLeft: 6 }}>{sub}</span>}
      </div>
      {right}
    </div>
  );
}

Object.assign(window, { DashboardA, DashboardB, DashboardC, MetricCard, PageWrap, SectionTitle, RangeTabs, HoldingsPreviewTable });
