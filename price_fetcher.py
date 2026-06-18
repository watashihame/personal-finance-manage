"""Price-refresh orchestration: FX rates, the per-market provider dispatch, the
price cache / history upserts, manual overrides, and portfolio-value snapshots.

The actual data-source fetchers and their per-market priority chains live in
:mod:`price_providers`; this module walks those chains, persists the results, and
falls back to the last cached price when every source for a symbol is down.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import requests
from sqlalchemy import select

from models import PriceCache, ExchangeRate, Transaction, Holding, PriceHistory, get_session
from price_providers import MARKETS, classify_market, classify_bucket, fetch_bucket

logger = logging.getLogger(__name__)

CACHE_TTL_MINUTES = 15
RATE_TTL_HOURS = 1
FALLBACK_RATES = {"USD": 7.25, "JPY": 0.048, "HKD": 0.93}

CHART_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]


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
# Cache / history upsert
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

def refresh_all_prices(holdings, rates: dict | None = None, market: str = "all") -> dict:
    """
    Fetch prices for all holdings via per-market provider chains. Skip symbols
    with is_manual=True.

    market: "all" | "cn" | "us" | "jp" | "crypto"
        - "cn" 含 A股 / 场外基金 / ICBC 黄金
        - 每个市场按优先级走多源回退链（见 price_providers.CHAINS），逐 symbol 回退
        - 某 symbol 所有实时源都失败时，估值沿用 price_cache 里的上次价格（不写
          price_history、不刷新缓存时间戳），避免持仓估值缺失
        - 非 "all" 时只更新被选中市场的 price_cache / price_history，
          不写当日的 portfolio_value_history 快照（避免半截数据覆盖完整快照）
    Returns {"updated": n, "failed": n, "stale": n, "errors": [...], "timestamp": str, "market": str}
    """
    if market not in MARKETS:
        raise ValueError(f"unknown market {market!r}, expected one of {MARKETS}")
    session = get_session()
    try:
        cache_rows = session.execute(select(PriceCache)).scalars().all()
        cache_by_symbol = {row.symbol: row for row in cache_rows}
        manual_symbols = {row.symbol for row in cache_rows if row.is_manual}

        symbols_to_fetch = [
            h.symbol for h in holdings
            if h.symbol not in manual_symbols
            and h.asset_type != "cash"
            and h.quantity > 1e-6
            and (market == "all" or classify_market(h.symbol) == market)
        ]

        # 按 bucket 分组，每个 bucket 的回退链并行执行
        buckets: dict[str, list[str]] = {}
        for sym in symbols_to_fetch:
            buckets.setdefault(classify_bucket(sym), []).append(sym)

        resolved: dict[str, tuple[float | None, str | None]] = {}
        if buckets:
            with ThreadPoolExecutor(max_workers=len(buckets)) as pool:
                futures = {pool.submit(fetch_bucket, b, syms): b for b, syms in buckets.items()}
                for future in as_completed(futures):
                    b = futures[future]
                    try:
                        resolved.update(future.result())
                    except Exception as exc:
                        logger.error("price bucket %s failed: %s", b, exc)

        holding_map = {h.symbol: h for h in holdings}
        updated = 0
        failed = 0
        stale = 0
        errors: list[str] = []
        snapshot_prices: dict[str, float] = {}  # symbol -> price used for value snapshot

        for sym, (price, source) in resolved.items():
            if price is not None:
                h = holding_map.get(sym)
                currency = h.currency if h else "CNY"
                _upsert_cache(session, sym, price, currency, source or "auto")
                _upsert_history(session, sym, price, currency, source or "auto")
                snapshot_prices[sym] = price
                updated += 1
                continue
            cached = cache_by_symbol.get(sym)
            if cached is not None and cached.price is not None:
                # 实时源全部失败：估值沿用上次缓存价，缓存本身保持不动
                snapshot_prices[sym] = cached.price
                stale += 1
                errors.append(f"{sym}: 实时源不可用，估值沿用缓存价")
            else:
                failed += 1
                errors.append(f"{sym}: 获取失败")

        # --- 组合价值快照（仅全量刷新时写，避免分市场刷新覆盖完整快照） ---
        if market == "all":
            if rates is None:
                rates = fetch_exchange_rates()
            rates_cny = dict(rates)
            rates_cny["CNY"] = 1.0
            today = datetime.now(timezone.utc).date()

            holding_values: dict[str, float] = {}
            for sym, price in snapshot_prices.items():
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
            "stale": stale,
            "errors": errors,
            "market": market,
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


def backfill_value_history(session) -> int:
    """遍历 price_history 中已有的历史日期，按当时持仓数量回填 portfolio_value_history。

    返回处理的天数。调用方负责提交 session（函数内会 commit 一次）。
    """
    holdings = session.execute(select(Holding)).scalars().all()
    if not holdings:
        return 0

    dates = session.execute(
        select(PriceHistory.date).distinct().order_by(PriceHistory.date)
    ).scalars().all()
    if not dates:
        return 0

    rates = fetch_exchange_rates()
    rates_cny = dict(rates)
    rates_cny["CNY"] = 1.0

    all_history = session.execute(select(PriceHistory)).scalars().all()
    ph_map: dict[tuple, float] = {}
    for ph in all_history:
        ph_map[(ph.symbol, ph.date)] = ph.price

    holding_map = {h.symbol: h for h in holdings}
    days_processed = 0

    for d in dates:
        holding_values: dict[str, float] = {}
        for h in holdings:
            price = ph_map.get((h.symbol, d))
            if price is None:
                continue
            qty = compute_quantity_at_date(session, h.id, d)
            if qty <= 0:
                continue
            fx = rates_cny.get(h.currency, 1.0)
            holding_values[h.symbol] = qty * price * fx

        if not holding_values:
            continue

        for sym, val in holding_values.items():
            _upsert_portfolio_value_history(session, d, sym, "holding", val)

        tag_totals: dict[str, float] = {}
        for sym, val in holding_values.items():
            h = holding_map.get(sym)
            if h is None:
                continue
            for tag in (t.strip() for t in (h.tags or "").split(",") if t.strip()):
                tag_totals[tag] = tag_totals.get(tag, 0.0) + val
        for tag, val in tag_totals.items():
            _upsert_portfolio_value_history(session, d, tag, "tag", val)

        total_val = sum(holding_values.values())
        _upsert_portfolio_value_history(session, d, "total", "total", total_val)

        days_processed += 1

    session.commit()
    return days_processed
