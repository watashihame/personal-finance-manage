/* global React */
// Real-API backed data layer. No mock data.

const FX = { CNY: 1, USD: 7.25, JPY: 0.048, HKD: 0.93, EUR: 7.8, GBP: 9.1 };

function computeRow(h) {
  const isCash = h.type === "cash" || h.asset_type === "cash" || h.assetType === "cash";
  const price = isCash ? 1.0 : (h.currentPrice ?? h.current_price);
  const fx = FX[h.currency] || 1;
  const valueCny = h.valueCny ?? (h.quantity * price * fx);
  const costCny  = h.costCny  ?? (h.quantity * h.costPrice * fx);
  const pnlCny   = h.pnlCny   ?? (valueCny - costCny);
  const pnlPct   = h.pnlPct   ?? (costCny > 0 ? (pnlCny / costCny) * 100 : 0);
  return { ...h, currentPrice: price, valueCny, costCny, pnlCny, pnlPct };
}

const fmt = {
  cny:  (v, dp = 2) => "¥" + Number(v).toLocaleString("zh-CN", { minimumFractionDigits: dp, maximumFractionDigits: dp }),
  num:  (v, dp = 2) => Number(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp }),
  qty:  (v) => Number(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 4 }),
  pct:  (v) => v == null ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "%",
  pctSigned: (v) => v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%",
  signed: (v, dp = 2) => v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toLocaleString("zh-CN", { minimumFractionDigits: dp, maximumFractionDigits: dp }),
  k: (v) => v >= 1e8 ? (v / 1e8).toFixed(2) + "亿" : v >= 1e4 ? (v / 1e4).toFixed(2) + "万" : v.toLocaleString("zh-CN", { maximumFractionDigits: 0 }),
};

const MARKET_LABEL = { CN: "A股", US: "美股", JP: "日股", CRYPTO: "加密", OTHER: "其他" };
const TX_TYPE_ZH = { BUY: "买入", SELL: "卖出", TRANSFER_IN: "转入", TRANSFER_OUT: "转出" };

// Global state (populated by initFromAPI)
let HOLDINGS = [];
let TOTAL_VALUE = 0, TOTAL_COST = 0, TOTAL_PNL = 0, TOTAL_PNL_PCT = 0;
let DAY_PNL = 0, DAY_PNL_PCT = 0;
let HISTORY = [];
let TAG_BUCKETS = [];
let TOP_GAINERS = [], TOP_LOSERS = [], TOP_DAY = [];
let SAMPLE_TRANSACTIONS = [];
let PORTFOLIO_TRANSACTIONS = [];

async function initFromAPI() {
  const [holdingsRes, portfolioRes, tagsRes, ratesRes, historyRes] = await Promise.all([
    fetch("/api/holdings"),
    fetch("/api/portfolio"),
    fetch("/api/tags"),
    fetch("/api/exchange-rates"),
    fetch("/api/portfolio-value-history"),
  ]);

  if (holdingsRes.status === 401) throw new Error("Unauthorized");

  const [holdings, portfolio, tags, rates, history] = await Promise.all([
    holdingsRes.json(),
    portfolioRes.json(),
    tagsRes.json(),
    ratesRes.json(),
    historyRes.json(),
  ]);

  Object.assign(FX, rates);

  HOLDINGS        = holdings;
  TOTAL_VALUE     = portfolio.totalValueCny;
  TOTAL_COST      = portfolio.totalCostCny;
  TOTAL_PNL       = portfolio.totalPnlCny;
  TOTAL_PNL_PCT   = portfolio.totalPnlPct;
  DAY_PNL         = portfolio.dayPnl;
  DAY_PNL_PCT     = portfolio.dayPnlPct;
  HISTORY         = (history.dates || []).map((d, i) => ({ date: d, value: history.values[i] }));
  TAG_BUCKETS     = tags.map(t => ({ tag: t.tag, value: t.valueCny }));
  TOP_GAINERS     = [...HOLDINGS].sort((a, b) => b.pnlPct - a.pnlPct).slice(0, 3);
  TOP_LOSERS      = [...HOLDINGS].sort((a, b) => a.pnlPct - b.pnlPct).slice(0, 3);
  TOP_DAY         = [...HOLDINGS].filter(h => h.daily != null)
                                 .sort((a, b) => Math.abs(b.daily) - Math.abs(a.daily))
                                 .slice(0, 5);

  const txRes = await fetch("/api/transactions");
  const txData = txRes.ok ? await txRes.json() : [];
  const holdingMap = Object.fromEntries(HOLDINGS.map(h => [h.id, h]));
  PORTFOLIO_TRANSACTIONS = txData.map(t => {
    const h = holdingMap[t.holdingId] || {};
    return {
      id: t.id, date: t.date,
      type: TX_TYPE_ZH[t.type] || t.type,
      symbol: h.symbol || "",
      name: h.name || "",
      quantity: t.quantity,
      price: t.unitPrice,
      currency: h.currency || "CNY",
      fee: t.fee || 0,
      counterpartySymbol: t.counterpartySymbol || null,
      note: t.notes,
    };
  });
  SAMPLE_TRANSACTIONS = PORTFOLIO_TRANSACTIONS.slice(0, 10);

  _syncWindow();
}

function _syncWindow() {
  Object.assign(window, {
    HOLDINGS, TOTAL_VALUE, TOTAL_COST, TOTAL_PNL, TOTAL_PNL_PCT,
    DAY_PNL, DAY_PNL_PCT, HISTORY, TAG_BUCKETS,
    TOP_GAINERS, TOP_LOSERS, TOP_DAY, SAMPLE_TRANSACTIONS, PORTFOLIO_TRANSACTIONS,
    FX,
  });
}

_syncWindow();

Object.assign(window, { computeRow, fmt, MARKET_LABEL, TX_TYPE_ZH, initFromAPI });
