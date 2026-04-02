import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf
from sqlalchemy import select

from models import PriceCache, ExchangeRate, get_session

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

def refresh_all_prices(holdings) -> dict:
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
            h.symbol for h in holdings if h.symbol not in manual_symbols
        ]

        fund_syms   = [s for s in symbols_to_fetch if _is_cn_fund(s)]
        ashare_syms = [s for s in symbols_to_fetch if _is_ashare(s)]
        other_syms  = [s for s in symbols_to_fetch if not _is_ashare(s) and not _is_cn_fund(s)]

        all_results: dict[str, float | None] = {}
        if fund_syms:
            all_results.update(_fetch_eastmoney_fund(fund_syms))
        if ashare_syms:
            all_results.update(_fetch_tushare(ashare_syms))
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
            else:
                source = "yfinance"
            _upsert_cache(session, sym, price, currency, source)
            _upsert_history(session, sym, price, currency, source)
            updated += 1

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
