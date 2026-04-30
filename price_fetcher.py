import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
from sqlalchemy import select

from models import PriceCache, ExchangeRate, Transaction, get_session

logger = logging.getLogger(__name__)

CACHE_TTL_MINUTES = 15
RATE_TTL_HOURS = 1
FALLBACK_RATES = {"USD": 7.25, "JPY": 0.048, "HKD": 0.93}

CHART_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]


def _load_tushare_token() -> str | None:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token or token == "your_tushare_token_here":
        return None
    return token


def _is_ashare(symbol: str) -> bool:
    return symbol.upper().endswith(".SH") or symbol.upper().endswith(".SZ")


def _is_japanese(symbol: str) -> bool:
    return symbol.upper().endswith(".T")


def _is_crypto(symbol: str) -> bool:
    return "-USD" in symbol.upper() or "-USDT" in symbol.upper()


def _is_cn_fund(symbol: str) -> bool:
    """六位数字（含或不含 .OF 后缀）= A 股开放式基金"""
    return bool(re.match(r'^\d{6}(\.OF)?$', symbol, re.IGNORECASE))


ICBC_GOLD_URL = "https://mybank.icbc.com.cn/icbc/newperbank/perbank3/gold/goldaccrual_query_out.jsp"
ICBC_GOLD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://mybank.icbc.com.cn/",
}


def _is_icbc_gold(symbol: str) -> bool:
    return symbol.upper() == "ICBC-GOLD"


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------

def _get_cached_rates(session) -> dict[str, float]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RATE_TTL_HOURS)
    rows = session.execute(select(ExchangeRate)).scalars().all()
    if not rows:
        return {}
    # Check freshness of any row
    if all(r.fetched_at.replace(tzinfo=timezone.utc) < cutoff for r in rows):
        return {}
    return {r.from_currency: r.rate for r in rows}


def fetch_exchange_rates() -> dict[str, float]:
    """Return {currency: cny_rate}. Falls back to DB then hardcoded values."""
    session = get_session()
    try:
        cached = _get_cached_rates(session)
        if cached:
            return cached

        resp = requests.get(
            "https://open.er-api.com/v6/latest/CNY",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("rates", {})

        rates: dict[str, float] = {}
        for currency in ["USD", "JPY", "HKD", "EUR", "GBP"]:
            if currency in raw and raw[currency] != 0:
                # API returns "how many X per 1 CNY", invert to get "CNY per X"
                rates[currency] = 1.0 / raw[currency]

        now = datetime.now(timezone.utc)
        for currency, rate in rates.items():
            existing = session.execute(
                select(ExchangeRate).where(ExchangeRate.from_currency == currency)
            ).scalar_one_or_none()
            if existing:
                existing.rate = rate
                existing.fetched_at = now
            else:
                session.add(ExchangeRate(
                    from_currency=currency,
                    to_currency="CNY",
                    rate=rate,
                    fetched_at=now,
                ))
        session.commit()
        return rates

    except Exception as exc:
        logger.warning("Failed to fetch exchange rates: %s", exc)
        # Fall back to last DB values, else hardcoded
        rows = session.execute(select(ExchangeRate)).scalars().all()
        if rows:
            return {r.from_currency: r.rate for r in rows}
        return FALLBACK_RATES.copy()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# A-share prices via Tushare
# ---------------------------------------------------------------------------

def _fetch_tushare(symbols: list[str]) -> dict[str, float | None]:
    token = _load_tushare_token()
    if not token:
        logger.warning("Tushare token not configured")
        return {s: None for s in symbols}

    try:
        import tushare as ts
        pro = ts.pro_api(token)

        results: dict[str, float | None] = {}
        # Tushare daily() can accept comma-separated ts_codes
        ts_codes = ",".join(symbols)
        df = pro.daily(ts_code=ts_codes, limit=len(symbols))
        if df is None or df.empty:
            return {s: None for s in symbols}

        # Keep only the most recent row per symbol
        df = df.sort_values("trade_date", ascending=False)
        df = df.drop_duplicates(subset="ts_code", keep="first")
        price_map = dict(zip(df["ts_code"], df["close"]))

        for sym in symbols:
            results[sym] = float(price_map[sym]) if sym in price_map else None
        return results

    except Exception as exc:
        logger.error("Tushare fetch failed: %s", exc)
        return {s: None for s in symbols}


# ---------------------------------------------------------------------------
# CN open-end fund NAV via 天天基金网 (eastmoney) — free, no token required
# ---------------------------------------------------------------------------

_EASTMONEY_HEADERS = {"Referer": "https://fundf10.eastmoney.com/"}
_EASTMONEY_URL = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=1"


def _fetch_one_eastmoney(sym: str) -> tuple[str, float | None]:
    code = re.sub(r'\.OF$', '', sym, flags=re.IGNORECASE)
    for attempt in range(2):
        try:
            resp = requests.get(
                _EASTMONEY_URL.format(code=code),
                headers=_EASTMONEY_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            lst = resp.json().get("Data", {}).get("LSJZList", [])
            return sym, float(lst[0]["DWJZ"]) if lst else None
        except Exception as exc:
            if attempt == 1:
                logger.warning("eastmoney fund_nav failed for %s: %s", sym, exc)
    return sym, None


def _fetch_eastmoney_fund(symbols: list[str]) -> dict[str, float | None]:
    """Fetch unit NAV (单位净值) from eastmoney concurrently for each fund symbol."""
    results: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as pool:
        futures = {pool.submit(_fetch_one_eastmoney, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, price = future.result()
            results[sym] = price
    return results


# ---------------------------------------------------------------------------
# ICBC gold accumulation (工银积存金) price scraper
# ---------------------------------------------------------------------------

class _LegacySSLAdapter(requests.adapters.HTTPAdapter):
    """Allow legacy TLS renegotiation for older bank servers (e.g., ICBC)."""
    def init_poolmanager(self, *args, **kwargs):
        import ssl
        ctx = ssl.create_default_context()
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _fetch_icbc_gold(symbols: list[str]) -> dict[str, float | None]:
    """从工行积存金页面抓取实时主动积存价格（CNY/克）。

    页面 HTML 中含有 id="activeprice_<prodcode>" 的 <td>，初始值即为实时价格。
    """
    try:
        from bs4 import BeautifulSoup
        session = requests.Session()
        session.mount("https://", _LegacySSLAdapter())
        resp = session.get(ICBC_GOLD_URL, headers=ICBC_GOLD_HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = "gbk"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 策略1：id="activeprice_<prodcode>" 即实时主动积存价格
        price = None
        tag = soup.find(id=re.compile(r'^activeprice_'))
        if tag:
            candidate = float(tag.get_text(strip=True))
            if 300 < candidate < 3000:
                price = candidate

        # 策略2：全文正则回退 — id="activeprice_..." 后跟数字
        if price is None:
            m = re.search(r'id="activeprice_[^"]*"[^>]*>(\d{3,4}\.\d{2})', resp.text)
            if m:
                candidate = float(m.group(1))
                if 300 < candidate < 3000:
                    price = candidate

        if price is None:
            logger.warning("ICBC gold: 未找到 activeprice 字段")
        else:
            logger.info("ICBC gold price fetched: %.2f CNY/g", price)

        return {sym: price for sym in symbols}
    except Exception as exc:
        logger.error("ICBC gold fetch failed: %s", exc)
        return {sym: None for sym in symbols}


# ---------------------------------------------------------------------------
# US / JP / Crypto prices via yfinance
# ---------------------------------------------------------------------------

def _fetch_yfinance(symbols: list[str]) -> dict[str, float | None]:
    if not symbols:
        return {}
    results: dict[str, float | None] = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                price = tickers.tickers[sym].fast_info.last_price
                results[sym] = float(price) if price is not None else None
            except Exception as exc:
                logger.warning("yfinance failed for %s: %s", sym, exc)
                results[sym] = None
    except Exception as exc:
        logger.error("yfinance batch fetch failed: %s", exc)
        results = {s: None for s in symbols}
    return results


# ---------------------------------------------------------------------------
# Cache upsert
# ---------------------------------------------------------------------------

def compute_quantity_at_date(session, holding_id: int, target_date) -> float:
    """从 transactions 推算某持仓在 target_date（含）时的实际持有数量。"""
    txs = session.execute(
        select(Transaction)
        .where(Transaction.holding_id == holding_id, Transaction.tx_date <= target_date)
        .order_by(Transaction.tx_date, Transaction.id)
    ).scalars().all()
    total_qty = 0.0
    total_cost = 0.0
    for tx in txs:
        if tx.tx_type in ("BUY", "TRANSFER_IN"):
            total_cost += tx.quantity * tx.unit_price + (tx.fee or 0.0)
            total_qty += tx.quantity
        elif tx.tx_type in ("SELL", "TRANSFER_OUT"):
            if total_qty > 0:
                fraction = tx.quantity / total_qty
                total_cost -= total_cost * fraction
            total_qty -= tx.quantity
    return max(total_qty, 0.0)


def _upsert_portfolio_value_history(session, date, scope: str, scope_type: str, value_cny: float):
    from models import PortfolioValueHistory
    existing = session.execute(
        select(PortfolioValueHistory).where(
            PortfolioValueHistory.date == date,
            PortfolioValueHistory.scope == scope,
        )
    ).scalar_one_or_none()
    if existing:
        existing.value_cny = value_cny
    else:
        session.add(PortfolioValueHistory(
            date=date, scope=scope, scope_type=scope_type, value_cny=value_cny
        ))


def _upsert_history(session, symbol: str, price: float, currency: str, source: str):
    from models import PriceHistory
    today = datetime.now(timezone.utc).date()
    existing = session.execute(
        select(PriceHistory).where(PriceHistory.symbol == symbol, PriceHistory.date == today)
    ).scalar_one_or_none()
    if existing:
        existing.price = price
        existing.currency = currency
        existing.source = source
    else:
        session.add(PriceHistory(symbol=symbol, date=today, price=price, currency=currency, source=source))


def _upsert_cache(session, symbol: str, price: float, currency: str, source: str):
    existing = session.execute(
        select(PriceCache).where(PriceCache.symbol == symbol)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing:
        existing.price = price
        existing.currency = currency
        existing.source = source
        existing.fetched_at = now
        existing.is_manual = False
    else:
        session.add(PriceCache(
            symbol=symbol,
            price=price,
            currency=currency,
            source=source,
            fetched_at=now,
            is_manual=False,
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_all_prices(holdings, rates: dict | None = None) -> dict:
    """
    Fetch prices for all holdings. Skip symbols with is_manual=True.
    Returns {"updated": n, "failed": n, "errors": [...], "timestamp": str}
    """
    session = get_session()
    try:
        # Find which symbols have manual override
        manual_symbols: set[str] = set()
        cache_rows = session.execute(select(PriceCache)).scalars().all()
        for row in cache_rows:
            if row.is_manual:
                manual_symbols.add(row.symbol)

        symbols_to_fetch = [
            h.symbol for h in holdings
            if h.symbol not in manual_symbols and h.asset_type != "cash"
        ]

        fund_syms      = [s for s in symbols_to_fetch if _is_cn_fund(s)]
        ashare_syms    = [s for s in symbols_to_fetch if _is_ashare(s)]
        icbc_gold_syms = [s for s in symbols_to_fetch if _is_icbc_gold(s)]
        other_syms     = [s for s in symbols_to_fetch if
                          not _is_ashare(s) and not _is_cn_fund(s) and not _is_icbc_gold(s)]

        all_results: dict[str, float | None] = {}
        if fund_syms:
            all_results.update(_fetch_eastmoney_fund(fund_syms))
        if ashare_syms:
            all_results.update(_fetch_tushare(ashare_syms))
        if icbc_gold_syms:
            all_results.update(_fetch_icbc_gold(icbc_gold_syms))
        if other_syms:
            all_results.update(_fetch_yfinance(other_syms))

        # Determine currency per symbol
        holding_map = {h.symbol: h for h in holdings}

        updated = 0
        failed = 0
        errors = []

        for sym, price in all_results.items():
            if price is None:
                failed += 1
                errors.append(f"{sym}: 获取失败")
                continue
            h = holding_map.get(sym)
            currency = h.currency if h else "CNY"
            if _is_cn_fund(sym):
                source = "eastmoney"
            elif _is_ashare(sym):
                source = "tushare"
            elif _is_icbc_gold(sym):
                source = "icbc"
            else:
                source = "yfinance"
            _upsert_cache(session, sym, price, currency, source)
            _upsert_history(session, sym, price, currency, source)
            updated += 1

        # --- 组合价值快照 ---
        if rates is None:
            rates = fetch_exchange_rates()
        rates_cny = dict(rates)
        rates_cny["CNY"] = 1.0
        today = datetime.now(timezone.utc).date()

        holding_values: dict[str, float] = {}
        for sym, price in all_results.items():
            if price is None:
                continue
            h = holding_map.get(sym)
            if h is None:
                continue
            qty = compute_quantity_at_date(session, h.id, today)
            if qty <= 0:
                continue
            fx = rates_cny.get(h.currency, 1.0)
            holding_values[sym] = qty * price * fx

        # Add cash holdings (price = 1.0, no historical quantity needed)
        for h in holdings:
            if h.asset_type != "cash":
                continue
            if h.quantity <= 0:
                continue
            fx = rates_cny.get(h.currency, 1.0)
            holding_values[h.symbol] = h.quantity * 1.0 * fx

        for sym, val in holding_values.items():
            _upsert_portfolio_value_history(session, today, sym, "holding", val)

        tag_totals: dict[str, float] = {}
        for sym, val in holding_values.items():
            h = holding_map.get(sym)
            if h is None:
                continue
            for tag in (t.strip() for t in (h.tags or "").split(",") if t.strip()):
                tag_totals[tag] = tag_totals.get(tag, 0.0) + val
        for tag, val in tag_totals.items():
            _upsert_portfolio_value_history(session, today, tag, "tag", val)

        total_val = sum(holding_values.values())
        if total_val > 0:
            _upsert_portfolio_value_history(session, today, "total", "total", total_val)
        # --- end snapshot ---

        session.commit()
        return {
            "updated": updated,
            "failed": failed,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
    finally:
        session.close()


def set_manual_price(symbol: str, price: float, currency: str) -> None:
    """Write a manual price override and mark is_manual=True."""
    session = get_session()
    try:
        existing = session.execute(
            select(PriceCache).where(PriceCache.symbol == symbol)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing:
            existing.price = price
            existing.currency = currency
            existing.source = "manual"
            existing.fetched_at = now
            existing.is_manual = True
        else:
            session.add(PriceCache(
                symbol=symbol,
                price=price,
                currency=currency,
                source="manual",
                fetched_at=now,
                is_manual=True,
            ))
        session.commit()
    finally:
        session.close()


def clear_manual_override(symbol: str) -> None:
    """Remove manual override flag so auto-fetch resumes."""
    session = get_session()
    try:
        row = session.execute(
            select(PriceCache).where(PriceCache.symbol == symbol)
        ).scalar_one_or_none()
        if row:
            row.is_manual = False
            session.commit()
    finally:
        session.close()
