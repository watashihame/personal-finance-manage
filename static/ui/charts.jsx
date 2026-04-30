/* global React */
// Shared SVG chart primitives — minimal, terminal-feel.
// All components are inline SVG with CSS variables for theming.

const { useMemo, useState, useEffect, useRef } = React;

// --- Sparkline ----------------------------------------------------------
function Sparkline({ data, width = 80, height = 22, stroke, fill = false, strokeWidth = 1.25 }) {
  if (!data || data.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const dx = width / (data.length - 1);
  const points = data.map((v, i) => [i * dx, height - ((v - min) / range) * height]);
  const d = points.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const last = data[data.length - 1];
  const first = data[0];
  const color = stroke || (last >= first ? "var(--up)" : "var(--down)");
  const area = fill ? d + ` L${width.toFixed(1)},${height} L0,${height} Z` : null;
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {fill && <path d={area} fill={color} opacity="0.12" />}
      <path d={d} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// --- Line chart with grid + axis (NAV history) -------------------------
function LineChart({ data, height = 240, accent = "var(--fg)", showAxis = true, showArea = true, dense = false, markers = null }) {
  const ref = useRef(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) setW(e.contentRect.width);
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const padL = 44, padR = 12, padT = 12, padB = 22;
  const W = w, H = height;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const values = data.map(d => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const yPad = range * 0.08;
  const yMin = min - yPad;
  const yMax = max + yPad;
  const dx = innerW / (data.length - 1 || 1);
  const yToPx = v => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  const points = data.map((d, i) => [padL + i * dx, yToPx(d.value)]);
  const path = points.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const areaPath = path + ` L${(padL + innerW).toFixed(1)},${(padT + innerH).toFixed(1)} L${padL.toFixed(1)},${(padT + innerH).toFixed(1)} Z`;

  // Y ticks
  const yTicks = 4;
  const ticks = [];
  for (let i = 0; i <= yTicks; i++) {
    const v = yMin + ((yMax - yMin) * i) / yTicks;
    ticks.push({ v, y: yToPx(v) });
  }
  // X ticks (8 labels max)
  const xLabelEvery = Math.max(1, Math.ceil(data.length / (dense ? 6 : 6)));
  const xLabels = data.map((d, i) => ({ d, i, x: padL + i * dx })).filter((_, i) => i % xLabelEvery === 0);

  // Hover state
  const [hover, setHover] = useState(null);
  const [hoverMarker, setHoverMarker] = useState(null);
  const onMove = e => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left;
    const idx = Math.max(0, Math.min(data.length - 1, Math.round((x - padL) / dx)));
    setHover(idx);
  };
  const onLeave = () => { setHover(null); setHoverMarker(null); };

  // Map markers to data positions, then group transactions that fall on the same data point
  const dateIdx = {};
  data.forEach((d, i) => { dateIdx[d.date] = i; });
  const minDate = data.length ? data[0].date : null;
  const maxDate = data.length ? data[data.length - 1].date : null;
  const markerGroups = (() => {
    if (!markers || !markers.length) return [];
    const buckets = new Map();
    markers.forEach(m => {
      // Drop markers outside the visible window
      if (minDate && m.date < minDate) return;
      if (maxDate && m.date > maxDate) return;
      let idx = dateIdx[m.date];
      if (idx === undefined) {
        const t = new Date(m.date).getTime();
        let best = -1, bestDiff = Infinity;
        data.forEach((d, i) => {
          const diff = Math.abs(new Date(d.date).getTime() - t);
          if (diff < bestDiff) { bestDiff = diff; best = i; }
        });
        idx = best;
      }
      if (idx < 0) return;
      if (!buckets.has(idx)) buckets.set(idx, []);
      buckets.get(idx).push(m);
    });
    return [...buckets.entries()].map(([idx, txs]) => ({ idx, txs, x: points[idx][0], y: points[idx][1] }));
  })();

  const fmtY = v => v >= 10000 ? (v / 10000).toFixed(1) + "万" : Math.round(v).toLocaleString();

  return (
    <div ref={ref} style={{ width: "100%", position: "relative" }}>
      <svg width={W} height={H} onMouseMove={onMove} onMouseLeave={onLeave} style={{ display: "block" }}>
        {/* grid */}
        {showAxis && ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={padL + innerW} y1={t.y} y2={t.y} stroke="var(--grid-line)" strokeWidth="1" />
            <text x={padL - 6} y={t.y + 3} textAnchor="end" fontSize="10" fill="var(--fg-3)" fontFamily="var(--font-mono)">{fmtY(t.v)}</text>
          </g>
        ))}
        {/* x-labels */}
        {showAxis && xLabels.map((x, i) => (
          <text key={i} x={x.x} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--fg-3)" fontFamily="var(--font-mono)">
            {x.d.date.slice(5)}
          </text>
        ))}
        {/* area + line */}
        {showArea && <path d={areaPath} fill={accent} opacity="0.08" />}
        <path d={path} fill="none" stroke={accent} strokeWidth="1.5" strokeLinejoin="round">
          <animate attributeName="stroke-dasharray" from="2000 2000" to="2000 0" dur="0.8s" fill="freeze" />
        </path>
        {/* hover line */}
        {hover !== null && (
          <g>
            <line x1={points[hover][0]} x2={points[hover][0]} y1={padT} y2={padT + innerH} stroke="var(--fg-3)" strokeWidth="1" strokeDasharray="2 2" />
            <circle cx={points[hover][0]} cy={points[hover][1]} r="3.5" fill="var(--bg)" stroke={accent} strokeWidth="1.5" />
          </g>
        )}
        {/* transaction markers */}
        {markerGroups.map(({ idx, txs, x, y }) => {
          const buys = txs.filter(t => t.type === "买入").length;
          const sells = txs.filter(t => t.type === "卖出").length;
          const isBuy = buys > 0 && sells === 0;
          const isSell = sells > 0 && buys === 0;
          const color = isBuy ? "var(--up)" : isSell ? "var(--down)" : "var(--fg-2)";
          const isActive = hoverMarker === idx;
          const r = isActive ? 6 : 4.5;
          const glyph = isBuy ? "B" : isSell ? "S" : "•";
          return (
            <g key={idx} style={{ cursor: "pointer" }}
               onMouseEnter={() => setHoverMarker(idx)}
               onMouseLeave={() => setHoverMarker(null)}>
              {isActive && <circle cx={x} cy={y} r={r + 4} fill={color} opacity="0.18" />}
              <circle cx={x} cy={y} r={r} fill="var(--bg)" stroke={color} strokeWidth="1.5" />
              <text x={x} y={y + 2.5} textAnchor="middle" fontSize="7" fontWeight="700" fill={color} fontFamily="var(--font-mono)" pointerEvents="none">{glyph}</text>
              {txs.length > 1 && (
                <g pointerEvents="none">
                  <circle cx={x + 5.5} cy={y - 5.5} r="5" fill={color} stroke="var(--bg)" strokeWidth="1" />
                  <text x={x + 5.5} y={y - 3.5} textAnchor="middle" fontSize="7" fontWeight="700" fill="var(--bg)" fontFamily="var(--font-mono)">{txs.length}</text>
                </g>
              )}
              <circle cx={x} cy={y} r="11" fill="transparent" />
            </g>
          );
        })}
      </svg>
      {hover !== null && hoverMarker === null && (
        <div style={{
          position: "absolute",
          left: Math.min(points[hover][0] + 8, W - 140),
          top: Math.max(points[hover][1] - 36, 4),
          background: "var(--surface)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--r-2)",
          padding: "6px 10px",
          fontSize: "var(--fs-xs)",
          fontFamily: "var(--font-mono)",
          pointerEvents: "none",
          boxShadow: "var(--shadow-2)",
          whiteSpace: "nowrap",
        }}>
          <div style={{ color: "var(--fg-3)", fontSize: 10 }}>{data[hover].date}</div>
          <div style={{ fontWeight: 600 }}>¥{fmtY(data[hover].value)}</div>
        </div>
      )}
      {/* Marker tooltip — lists every transaction in the bucket */}
      {hoverMarker !== null && (() => {
        const grp = markerGroups.find(g => g.idx === hoverMarker);
        if (!grp) return null;
        const tipW = 252;
        const left = Math.min(Math.max(grp.x - tipW / 2, 4), W - tipW - 4);
        const estH = 30 + grp.txs.length * 36;
        const top = grp.y + 14 + estH > H ? Math.max(grp.y - 14 - estH, 4) : grp.y + 14;
        const curSym = (c) => c === "USD" ? "$" : c === "JPY" ? "¥" : "¥";
        return (
          <div style={{
            position: "absolute",
            left, top,
            width: tipW,
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-2)",
            padding: "10px 12px",
            fontSize: "var(--fs-xs)",
            pointerEvents: "none",
            boxShadow: "var(--shadow-2)",
            zIndex: 5,
          }}>
            <div style={{ color: "var(--fg-3)", fontSize: 10, fontFamily: "var(--font-mono)", marginBottom: 8, display: "flex", justifyContent: "space-between", paddingBottom: 6, borderBottom: "1px solid var(--border)" }}>
              <span>{grp.txs[0].date}</span>
              <span>组合净值 ¥{fmtY(data[hoverMarker].value)}</span>
            </div>
            {grp.txs.map((t, i) => {
              const isBuy = t.type === "买入";
              const color = isBuy ? "var(--up)" : "var(--down)";
              return (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "5px 0", borderTop: i ? "1px dashed var(--border)" : "none" }}>
                  <span style={{
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    width: 18, height: 16, fontSize: 9, fontWeight: 700, fontFamily: "var(--font-mono)",
                    color, border: `1px solid ${color}`, borderRadius: 3, flexShrink: 0, marginTop: 1,
                  }}>{isBuy ? "B" : "S"}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.name || t.symbol}</span>
                      <span style={{ fontFamily: "var(--font-mono)", color, fontWeight: 600, flexShrink: 0 }}>
                        {isBuy ? "+" : "−"}{fmt.qty(t.quantity)}
                      </span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, color: "var(--fg-3)", fontFamily: "var(--font-mono)", fontSize: 10, marginTop: 1 }}>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.symbol}</span>
                      <span style={{ flexShrink: 0 }}>@ {curSym(t.currency)}{fmt.num(t.price, t.price < 10 ? 4 : 2)}</span>
                    </div>
                    {t.note && <div style={{ color: "var(--fg-3)", fontSize: 10, marginTop: 1, fontStyle: "italic" }}>{t.note}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}
    </div>
  );
}

// --- Donut chart ------------------------------------------------------
function DonutChart({ data, size = 220, thickness = 26, palette }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = size / 2 - thickness / 2 - 2;
  const cx = size / 2, cy = size / 2;
  let angle = -Math.PI / 2;
  const segs = data.map((d, i) => {
    const frac = d.value / total;
    const a0 = angle;
    const a1 = angle + frac * Math.PI * 2;
    angle = a1;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    return {
      ...d,
      d: `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`,
      color: palette[i % palette.length],
      pct: frac * 100,
    };
  });
  const [hover, setHover] = useState(null);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {segs.map((s, i) => (
        <path
          key={i} d={s.d} fill="none"
          stroke={s.color}
          strokeWidth={hover === i ? thickness + 4 : thickness}
          strokeLinecap="butt"
          opacity={hover === null || hover === i ? 1 : 0.35}
          onMouseEnter={() => setHover(i)}
          onMouseLeave={() => setHover(null)}
          style={{ transition: "stroke-width 120ms, opacity 120ms", cursor: "pointer" }}
        />
      ))}
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize="11" fill="var(--fg-3)" fontFamily="var(--font-ui)">
        {hover !== null ? segs[hover].label : "总市值"}
      </text>
      <text x={cx} y={cy + 16} textAnchor="middle" fontSize="18" fontWeight="600" fill="var(--fg)" fontFamily="var(--font-mono)">
        {hover !== null ? fmt.k(segs[hover].value) : fmt.k(total)}
      </text>
      {hover !== null && (
        <text x={cx} y={cy + 32} textAnchor="middle" fontSize="10" fill="var(--fg-3)" fontFamily="var(--font-mono)">
          {segs[hover].pct.toFixed(1)}%
        </text>
      )}
    </svg>
  );
}

// --- Horizontal bar chart -----------------------------------------------
function BarList({ data, max, palette, valueFormat = v => fmt.k(v), labelMax = 18 }) {
  const m = max || Math.max(...data.map(d => d.value));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {data.map((d, i) => {
        const pct = (d.value / m) * 100;
        const color = palette ? palette[i % palette.length] : "var(--fg-2)";
        return (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) auto", gap: 12, alignItems: "center" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3, fontSize: "var(--fs-xs)" }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={d.label}>
                  {d.label.length > labelMax ? d.label.slice(0, labelMax) + "…" : d.label}
                </span>
                <span className="num muted-2" style={{ fontSize: "var(--fs-xxs)" }}>{valueFormat(d.value)}</span>
              </div>
              <div style={{ height: 6, background: "var(--bg-1)", borderRadius: 2, overflow: "hidden" }}>
                <div style={{
                  height: "100%",
                  width: pct + "%",
                  background: color,
                  transition: "width 600ms cubic-bezier(0.2,0,0,1)",
                }} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

Object.assign(window, { Sparkline, LineChart, DonutChart, BarList });
