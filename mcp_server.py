"""
MCP Server for the personal finance portfolio tracker.

Exposes portfolio data and operations to AI assistants (Claude Desktop / Claude Code
and remote agents) via the Model Context Protocol.

Transport modes
---------------
stdio (default) — local process, for Claude Code / Claude Desktop:
    python3 mcp_server.py

streamable-http — HTTP server, for remote agents:
    TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 python3 mcp_server.py
    Endpoint: http://<host>:<port>/mcp

Environment variables
---------------------
DATABASE_URL   SQLAlchemy URL (default: sqlite:///portfolio.db)
TUSHARE_TOKEN  Tushare Pro API token for A-share price fetching
TRANSPORT      'stdio' (default) or 'streamable-http'
MCP_HOST       Bind host for HTTP transport (default: 0.0.0.0)
MCP_PORT       Bind port for HTTP transport (default: 8000)
"""

import json
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Literal

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from models import (
    init_db, get_session, Holding, Transaction, PriceCache, ExchangeRate,
    PriceHistory, PortfolioValueHistory, recalculate_holding,
    find_paired_transaction, create_paired_transaction, apply_counterparty,
)
from price_fetcher import (
    refresh_all_prices,
    set_manual_price,
    clear_manual_override,
    fetch_exchange_rates,
    backfill_value_history,
)

logging.basicConfig(level=logging.WARNING)

# Initialise DB tables (creates them if they don't exist, same DATABASE_URL as Flask)
init_db()

MARKETS = ["CN", "US", "JP", "CRYPTO", "OTHER"]
ASSET_TYPES = ["stock", "etf", "fund", "bond", "crypto", "cash", "other"]
CURRENCIES = ["CNY", "USD", "JPY", "HKD", "EUR", "GBP"]

mcp = FastMCP(
    name="portfolio-tracker",
    instructions=(
        "Personal investment portfolio tracker. Tracks holdings across A-shares (CN), "
        "US stocks, Japanese stocks (JP), and cryptocurrencies (CRYPTO). "
        "All monetary totals are in CNY (Chinese Yuan) unless a currency field says otherwise. "
        "Call search_holdings first to find holding IDs before calling update/delete tools."
    ),
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8000")),
)


# ---------------------------------------------------------------------------
# Shared helpers (copied from app.py — no Flask dependency)
# ---------------------------------------------------------------------------

def _compute_portfolio(holdings, prices: dict, rates: dict) -> tuple[list[dict], float, float]:
    """Compute per-holding rows and totals. Returns (rows, total_value_cny, total_cost_cny)."""
    rows = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        is_cash = h.asset_type == "cash"
        pc = None
        if is_cash:
            current_price = 1.0
        else:
            pc = prices.get(h.symbol)
            current_price = pc.price if pc else None
        fx = rates.get(h.currency, 1.0)

        if current_price is not None:
            market_value_cny = h.quantity * current_price * fx
        else:
            market_value_cny = h.quantity * h.cost_price * fx  # fallback to cost

        cost_cny = h.quantity * h.cost_price * fx
        pnl_cny = market_value_cny - cost_cny
        pnl_pct = (pnl_cny / cost_cny * 100) if cost_cny else 0.0

        raw_tags = h.tags or ""
        tag_list = [t.strip() for t in raw_tags.split(",") if t.strip()]

        rows.append({
            "id": h.id,
            "name": h.name,
            "symbol": h.symbol,
            "market": h.market,
            "asset_type": h.asset_type,
            "currency": h.currency,
            "quantity": h.quantity,
            "cost_price": h.cost_price,
            "current_price": current_price,
            "market_value_cny": round(market_value_cny, 2),
            "cost_cny": round(cost_cny, 2),
            "pnl_cny": round(pnl_cny, 2),
            "pnl_pct": round(pnl_pct, 2),
            "tags": tag_list,
            "is_manual": pc.is_manual if pc else False,
            "price_stale": (
                pc is not None and
                (datetime.now(timezone.utc) - pc.fetched_at.replace(tzinfo=timezone.utc))
                > timedelta(minutes=15)
            ) if pc else True,
        })

        total_value += market_value_cny
        total_cost += cost_cny

    return rows, total_value, total_cost


def _load_portfolio_data() -> tuple[list[dict], float, float]:
    session = get_session()
    try:
        holdings = session.execute(select(Holding)).scalars().all()
        price_map = {
            r.symbol: r
            for r in session.execute(select(PriceCache)).scalars().all()
        }
        rates = {
            r.from_currency: r.rate
            for r in session.execute(select(ExchangeRate)).scalars().all()
        }
        rates["CNY"] = 1.0
        return _compute_portfolio(holdings, price_map, rates)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Resources (read-only, proactively surfaced to Claude)
# ---------------------------------------------------------------------------

@mcp.resource("portfolio://summary")
def resource_portfolio_summary() -> str:
    """Current portfolio totals: total market value (CNY), cost, P&L, and per-holding breakdown."""
    rows, total_value, total_cost = _load_portfolio_data()
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0
    return json.dumps({
        "total_value_cny": round(total_value, 2),
        "total_cost_cny": round(total_cost, 2),
        "total_pnl_cny": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "holding_count": len(rows),
        "holdings": rows,
    }, ensure_ascii=False, indent=2)


@mcp.resource("portfolio://holdings")
def resource_holdings_list() -> str:
    """Complete list of all holdings with current prices, market values (CNY), P&L, and tags."""
    rows, _, _ = _load_portfolio_data()
    return json.dumps(rows, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tools — Read
# ---------------------------------------------------------------------------

@mcp.tool()
def get_portfolio_summary() -> str:
    """
    Get the full portfolio summary: total market value (CNY), total cost, overall P&L,
    and a complete per-holding breakdown sorted by market value descending.
    """
    try:
        rows, total_value, total_cost = _load_portfolio_data()
        rows_sorted = sorted(rows, key=lambda r: r["market_value_cny"], reverse=True)
        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0
        return json.dumps({
            "total_value_cny": round(total_value, 2),
            "total_cost_cny": round(total_cost, 2),
            "total_pnl_cny": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "holding_count": len(rows_sorted),
            "holdings": rows_sorted,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def search_holdings(q: str = "") -> str:
    """
    Search holdings by name or symbol (case-insensitive substring match).
    Pass an empty string to list all holdings.
    Returns id, name, symbol, market, asset_type, currency, quantity, cost_price, tags.
    """
    try:
        session = get_session()
        try:
            holdings = session.execute(select(Holding)).scalars().all()
            q_lower = q.strip().lower()
            results = [
                {
                    "id": h.id,
                    "name": h.name,
                    "symbol": h.symbol,
                    "market": h.market,
                    "asset_type": h.asset_type,
                    "currency": h.currency,
                    "quantity": h.quantity,
                    "cost_price": h.cost_price,
                    "tags": [t.strip() for t in (h.tags or "").split(",") if t.strip()],
                    "notes": h.notes or "",
                }
                for h in holdings
                if not q_lower or q_lower in h.name.lower() or q_lower in h.symbol.lower()
            ]
            return json.dumps(results, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_holding_detail(holding_id: int) -> str:
    """
    Get full detail for one holding: current price/value/P&L, tags, plus all transactions
    and the last 60 days of price history (sparkline). Use search_holdings first to find the ID.
    """
    try:
        rows, _, _ = _load_portfolio_data()
        row = next((r for r in rows if r["id"] == holding_id), None)
        if row is None:
            return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

        session = get_session()
        try:
            txs = session.execute(
                select(Transaction)
                .where(Transaction.holding_id == holding_id)
                .order_by(Transaction.tx_date.desc(), Transaction.id.desc())
            ).scalars().all()

            from datetime import date as dt_date
            cutoff = dt_date.today() - timedelta(days=60)
            spark = session.execute(
                select(PriceHistory.price)
                .where(PriceHistory.symbol == row["symbol"], PriceHistory.date >= cutoff)
                .order_by(PriceHistory.date)
            ).scalars().all()

            return json.dumps({
                **row,
                "sparkline_60d": list(spark),
                "transactions": [
                    {
                        "id": t.id,
                        "tx_type": t.tx_type,
                        "tx_date": t.tx_date.isoformat(),
                        "quantity": t.quantity,
                        "unit_price": t.unit_price,
                        "fee": t.fee or 0.0,
                        "notes": t.notes or "",
                        "counterparty_id": t.counterparty_id,
                    }
                    for t in txs
                ],
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_tags() -> str:
    """
    Get all tags currently in use, with the total CNY market value and percentage of
    portfolio they represent, sorted by value descending.
    """
    try:
        rows, total_value, _ = _load_portfolio_data()
        tag_totals: dict[str, float] = {}
        for r in rows:
            for tag in r["tags"]:
                tag_totals[tag] = tag_totals.get(tag, 0.0) + r["market_value_cny"]
        result = [
            {
                "tag": tag,
                "value_cny": round(val, 2),
                "pct": round(val / total_value * 100, 2) if total_value else 0.0,
            }
            for tag, val in sorted(tag_totals.items(), key=lambda x: -x[1])
        ]
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_price_history(symbol: str) -> str:
    """
    Get the full daily price history for a symbol from the price_history table
    (populated by refresh_prices runs). Returns dates and prices in chronological order.
    """
    try:
        symbol = symbol.strip().upper()
        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"}, ensure_ascii=False)
        session = get_session()
        try:
            rows = session.execute(
                select(PriceHistory)
                .where(PriceHistory.symbol == symbol)
                .order_by(PriceHistory.date)
            ).scalars().all()
            return json.dumps({
                "symbol": symbol,
                "currency": rows[-1].currency if rows else "",
                "dates": [r.date.isoformat() for r in rows],
                "prices": [r.price for r in rows],
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_portfolio_value_history() -> str:
    """
    Get the daily total portfolio value (CNY) over time from snapshots in
    portfolio_value_history. Use backfill_value_history first if the series is empty.
    """
    try:
        session = get_session()
        try:
            rows = session.execute(
                select(PortfolioValueHistory)
                .where(PortfolioValueHistory.scope == "total")
                .order_by(PortfolioValueHistory.date)
            ).scalars().all()
            return json.dumps({
                "dates": [r.date.isoformat() for r in rows],
                "values_cny": [r.value_cny for r in rows],
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_holding_value_history(symbol: str) -> str:
    """
    Get the daily market value (CNY) over time for one holding, from snapshots in
    portfolio_value_history (scope_type='holding').
    """
    try:
        symbol = symbol.strip().upper()
        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"}, ensure_ascii=False)
        session = get_session()
        try:
            rows = session.execute(
                select(PortfolioValueHistory)
                .where(
                    PortfolioValueHistory.scope == symbol,
                    PortfolioValueHistory.scope_type == "holding",
                )
                .order_by(PortfolioValueHistory.date)
            ).scalars().all()
            holding = session.execute(
                select(Holding).where(Holding.symbol == symbol)
            ).scalar_one_or_none()
            return json.dumps({
                "symbol": symbol,
                "name": holding.name if holding else symbol,
                "dates": [r.date.isoformat() for r in rows],
                "values_cny": [r.value_cny for r in rows],
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_tag_value_history(tag: str) -> str:
    """
    Get the daily aggregated market value (CNY) over time for all holdings carrying a
    given tag, from snapshots in portfolio_value_history (scope_type='tag').
    """
    try:
        tag = tag.strip()
        if not tag:
            return json.dumps({"ok": False, "error": "tag is required"}, ensure_ascii=False)
        session = get_session()
        try:
            rows = session.execute(
                select(PortfolioValueHistory)
                .where(
                    PortfolioValueHistory.scope == tag,
                    PortfolioValueHistory.scope_type == "tag",
                )
                .order_by(PortfolioValueHistory.date)
            ).scalars().all()
            return json.dumps({
                "tag": tag,
                "dates": [r.date.isoformat() for r in rows],
                "values_cny": [r.value_cny for r in rows],
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_exchange_rates() -> str:
    """
    Get current CNY exchange rates for all tracked currencies (USD, JPY, HKD, EUR, GBP).
    Returns cached rates with their timestamps.
    """
    try:
        session = get_session()
        try:
            rate_rows = session.execute(select(ExchangeRate)).scalars().all()
            rates = {}
            timestamps = {}
            for r in rate_rows:
                rates[r.from_currency] = r.rate
                timestamps[r.from_currency] = r.fetched_at.isoformat()
            return json.dumps({
                "rates_to_cny": rates,
                "fetched_at": timestamps,
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tools — Write (holdings)
# ---------------------------------------------------------------------------

@mcp.tool()
def add_holding(
    name: str,
    symbol: str,
    market: Literal["CN", "US", "JP", "CRYPTO", "OTHER"],
    asset_type: Literal["stock", "etf", "fund", "bond", "crypto", "cash", "other"],
    currency: Literal["CNY", "USD", "JPY", "HKD", "EUR", "GBP"],
    quantity: float,
    cost_price: float,
    tags: str = "",
    notes: str = "",
) -> str:
    """
    Add a new investment holding to the portfolio.
    Symbol format: A-shares '600519.SH'/'000001.SZ', US stocks 'AAPL', JP stocks '7203.T', crypto 'BTC-USD'.
    tags: comma-separated string, e.g. '科技,长期持有'.
    """
    try:
        name = name.strip()
        symbol = symbol.strip().upper()
        if not name:
            return json.dumps({"ok": False, "error": "name is required"}, ensure_ascii=False)
        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"}, ensure_ascii=False)
        if asset_type == "cash":
            if quantity <= 0:
                return json.dumps({"ok": False, "error": "quantity must be > 0"}, ensure_ascii=False)
        else:
            if quantity <= 0:
                return json.dumps({"ok": False, "error": "quantity must be > 0"}, ensure_ascii=False)
            if cost_price <= 0:
                return json.dumps({"ok": False, "error": "cost_price must be > 0"}, ensure_ascii=False)

        session = get_session()
        try:
            h = Holding(
                name=name,
                symbol=symbol,
                market=market,
                asset_type=asset_type,
                currency=currency,
                quantity=quantity,
                cost_price=cost_price,
                tags=tags.strip(),
                notes=notes.strip(),
            )
            session.add(h)
            session.flush()
            tx = Transaction(
                holding_id=h.id,
                tx_type="BUY",
                tx_date=datetime.now(timezone.utc).date(),
                quantity=quantity,
                unit_price=cost_price,
                fee=0.0,
                notes="初始建仓",
            )
            session.add(tx)
            session.commit()
            session.refresh(h)
            return json.dumps({"ok": True, "id": h.id, "name": h.name, "symbol": h.symbol}, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def update_holding_quantity(
    holding_id: int,
    quantity: float | None = None,
    delta: float | None = None,
) -> str:
    """
    Update the quantity of an existing holding.
    Provide either 'quantity' (new absolute value) or 'delta' (amount to add/subtract, negative = sell).
    Use search_holdings first to find the holding ID.
    """
    try:
        if quantity is None and delta is None:
            return json.dumps({"ok": False, "error": "Provide either 'quantity' or 'delta'"}, ensure_ascii=False)
        if quantity is not None and delta is not None:
            return json.dumps({"ok": False, "error": "Provide only one of 'quantity' or 'delta', not both"}, ensure_ascii=False)

        session = get_session()
        try:
            h = session.get(Holding, holding_id)
            if not h:
                return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

            if quantity is not None:
                if quantity <= 0:
                    return json.dumps({"ok": False, "error": "quantity must be > 0"}, ensure_ascii=False)
                h.quantity = quantity
            else:
                new_qty = h.quantity + delta
                if new_qty <= 0:
                    return json.dumps({"ok": False, "error": f"Resulting quantity {new_qty} must be > 0"}, ensure_ascii=False)
                h.quantity = new_qty

            session.commit()
            return json.dumps({"ok": True, "id": h.id, "symbol": h.symbol, "quantity": h.quantity}, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def update_holding_tags(holding_id: int, tags: list[str]) -> str:
    """
    Replace the tags on a holding with a new list. Pass an empty list to clear all tags.
    Use search_holdings first to find the holding ID.
    """
    try:
        session = get_session()
        try:
            h = session.get(Holding, holding_id)
            if not h:
                return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

            cleaned = [t.strip() for t in tags if t.strip()]
            h.tags = ",".join(cleaned)
            session.commit()
            return json.dumps({"ok": True, "id": h.id, "symbol": h.symbol, "tags": cleaned}, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def update_holding(
    holding_id: int,
    name: str | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """
    Update a holding's display fields. Pass only the fields you want to change; omit
    others (or pass None). Use update_holding_quantity to change quantity, and
    add_transaction to record buys/sells (this tool does NOT recalculate cost_price).
    """
    try:
        if name is None and notes is None and tags is None:
            return json.dumps({"ok": False, "error": "Provide at least one of name/notes/tags"}, ensure_ascii=False)
        session = get_session()
        try:
            h = session.get(Holding, holding_id)
            if not h:
                return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

            if name is not None:
                name = name.strip()
                if not name:
                    return json.dumps({"ok": False, "error": "name cannot be empty"}, ensure_ascii=False)
                h.name = name
            if notes is not None:
                h.notes = notes.strip()
            if tags is not None:
                cleaned = [t.strip() for t in tags if t.strip()]
                h.tags = ",".join(cleaned)

            h.updated_at = datetime.now(timezone.utc)
            session.commit()
            return json.dumps({
                "ok": True,
                "id": h.id,
                "symbol": h.symbol,
                "name": h.name,
                "tags": [t.strip() for t in (h.tags or "").split(",") if t.strip()],
                "notes": h.notes or "",
            }, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def delete_holding(holding_id: int, confirm: bool) -> str:
    """
    Permanently delete a holding from the portfolio. This cannot be undone.
    You MUST pass confirm=True to confirm deletion. Use search_holdings first to verify the correct ID.
    """
    try:
        if not confirm:
            return json.dumps({"ok": False, "error": "Pass confirm=True to confirm deletion"}, ensure_ascii=False)

        session = get_session()
        try:
            h = session.get(Holding, holding_id)
            if not h:
                return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

            deleted_info = {"id": h.id, "name": h.name, "symbol": h.symbol}
            session.delete(h)
            session.commit()
            return json.dumps({"ok": True, "deleted": deleted_info}, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tools — Transactions
# ---------------------------------------------------------------------------

TX_TYPES = ["BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT"]


@mcp.tool()
def add_transaction(
    holding_id: int,
    tx_type: Literal["BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT"],
    quantity: float,
    unit_price: float,
    tx_date: str,
    fee: float = 0.0,
    notes: str = "",
    counterparty_holding_id: int = 0,
    counterparty_unit_price: float = 0.0,
) -> str:
    """
    Record a buy/sell/transfer transaction for an existing holding and update its quantity and cost_price.

    - BUY / TRANSFER_IN: increases quantity, updates weighted-average cost_price.
    - SELL / TRANSFER_OUT: decreases quantity, cost_price unchanged (average-cost method).
    - tx_date: ISO format date string, e.g. '2026-04-02'.
    - fee: transaction fee in the holding's currency (default 0).
    - counterparty_holding_id: optional, to create a paired transaction on another holding
      (default 0 = no counterparty). For BUY, creates SELL on counterparty; for SELL, creates BUY.
      When counterparty is a cash holding, the paired quantity is auto-calculated.
      When counterparty is another investment, provide counterparty_unit_price.

    Use search_holdings first to find the holding ID.
    """
    try:
        from datetime import date as dt_date
        try:
            parsed_date = dt_date.fromisoformat(tx_date)
        except ValueError:
            return json.dumps({"ok": False, "error": f"Invalid tx_date '{tx_date}', use YYYY-MM-DD"}, ensure_ascii=False)

        if quantity <= 0:
            return json.dumps({"ok": False, "error": "quantity must be > 0"}, ensure_ascii=False)
        if unit_price <= 0:
            return json.dumps({"ok": False, "error": "unit_price must be > 0"}, ensure_ascii=False)

        session = get_session()
        try:
            h = session.get(Holding, holding_id)
            if not h:
                return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

            tx = Transaction(
                holding_id=holding_id,
                tx_type=tx_type,
                tx_date=parsed_date,
                quantity=quantity,
                unit_price=unit_price,
                fee=fee,
                notes=notes.strip(),
            )
            session.add(tx)
            session.flush()

            paired_info = None
            cparty = None
            if counterparty_holding_id > 0:
                cparty = session.get(Holding, counterparty_holding_id)
                if not cparty:
                    return json.dumps({"ok": False, "error": f"Counterparty holding {counterparty_holding_id} not found"}, ensure_ascii=False)
                try:
                    cp_price = counterparty_unit_price if counterparty_unit_price > 0 else None
                    paired_tx = create_paired_transaction(session, tx, cparty, cp_price)
                except ValueError as exc:
                    return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                paired_info = {"transaction_id": paired_tx.id, "holding_id": cparty.id, "symbol": cparty.symbol}

            recalculate_holding(session, h)
            if cparty:
                recalculate_holding(session, cparty)
            session.commit()
            session.refresh(tx)

            result = {
                "ok": True,
                "transaction_id": tx.id,
                "holding_id": h.id,
                "symbol": h.symbol,
                "new_quantity": round(h.quantity, 6),
                "new_cost_price": round(h.cost_price, 6),
            }
            if paired_info:
                result["paired_transaction"] = paired_info
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def list_transactions(holding_id: int) -> str:
    """
    List all transactions for a holding, ordered by date ascending.
    Use search_holdings first to find the holding ID.
    """
    try:
        session = get_session()
        try:
            h = session.get(Holding, holding_id)
            if not h:
                return json.dumps({"ok": False, "error": f"Holding {holding_id} not found"}, ensure_ascii=False)

            txs = session.execute(
                select(Transaction)
                .where(Transaction.holding_id == holding_id)
                .order_by(Transaction.tx_date, Transaction.id)
            ).scalars().all()

            return json.dumps({
                "holding_id": holding_id,
                "name": h.name,
                "symbol": h.symbol,
                "current_quantity": h.quantity,
                "current_cost_price": h.cost_price,
                "transactions": [
                    {
                        "id": tx.id,
                        "tx_type": tx.tx_type,
                        "tx_date": tx.tx_date.isoformat(),
                        "quantity": tx.quantity,
                        "unit_price": tx.unit_price,
                        "fee": tx.fee,
                        "amount": round(tx.quantity * tx.unit_price + (tx.fee or 0), 2),
                        "notes": tx.notes,
                    }
                    for tx in txs
                ],
            }, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def update_transaction(
    tx_id: int,
    tx_type: Literal["BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT"] | None = None,
    tx_date: str | None = None,
    quantity: float | None = None,
    unit_price: float | None = None,
    fee: float | None = None,
    notes: str | None = None,
    counterparty_holding_id: int | None = None,
    counterparty_unit_price: float | None = None,
) -> str:
    """
    Update fields on an existing transaction and recompute the owning holding's
    quantity/cost_price. Pass only fields you want to change.

    Counterparty handling:
      - counterparty_holding_id = None (default): leave the existing pairing unchanged.
      - counterparty_holding_id = 0: explicitly UNLINK — deletes the paired
        transaction on the other holding and clears this tx's counterparty_id.
      - counterparty_holding_id > 0: SET or REPLACE the counterparty:
          * If currently unpaired, creates a new paired transaction.
          * If already paired to the same holding, syncs the paired tx's
            type/date/quantity/unit_price to match this tx.
          * If paired to a different holding, removes the old paired tx and
            creates a new one on the specified counterparty.
        For non-cash counterparties, you must also provide counterparty_unit_price.

    The paired holding is recomputed automatically when the pairing changes.
    """
    try:
        if all(v is None for v in (tx_type, tx_date, quantity, unit_price, fee, notes, counterparty_holding_id, counterparty_unit_price)):
            return json.dumps({"ok": False, "error": "Provide at least one field to update"}, ensure_ascii=False)

        session = get_session()
        try:
            tx = session.get(Transaction, tx_id)
            if not tx:
                return json.dumps({"ok": False, "error": f"Transaction {tx_id} not found"}, ensure_ascii=False)

            if tx_type is not None:
                tx.tx_type = tx_type
            if tx_date is not None:
                from datetime import date as dt_date
                try:
                    tx.tx_date = dt_date.fromisoformat(tx_date)
                except ValueError:
                    return json.dumps({"ok": False, "error": f"Invalid tx_date '{tx_date}', use YYYY-MM-DD"}, ensure_ascii=False)
            if quantity is not None:
                if quantity <= 0:
                    return json.dumps({"ok": False, "error": "quantity must be > 0"}, ensure_ascii=False)
                tx.quantity = quantity
            if unit_price is not None:
                if unit_price <= 0:
                    return json.dumps({"ok": False, "error": "unit_price must be > 0"}, ensure_ascii=False)
                tx.unit_price = unit_price
            if fee is not None:
                tx.fee = fee
            if notes is not None:
                tx.notes = notes.strip()

            session.flush()

            cp_price = counterparty_unit_price if (counterparty_unit_price is not None and counterparty_unit_price > 0) else None
            try:
                affected_cp, paired_tx = apply_counterparty(session, tx, counterparty_holding_id, cp_price)
            except ValueError as exc:
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

            h = session.get(Holding, tx.holding_id)
            if h is not None:
                recalculate_holding(session, h)
            for cph in affected_cp:
                recalculate_holding(session, cph)
            session.commit()

            result = {
                "ok": True,
                "id": tx.id,
                "holding_id": tx.holding_id,
                "has_paired": tx.counterparty_id is not None,
                "new_quantity": round(h.quantity, 6) if h else None,
                "new_cost_price": round(h.cost_price, 6) if h else None,
            }
            if paired_tx is not None:
                result["paired_transaction_id"] = paired_tx.id
            return json.dumps(result, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def delete_transaction(tx_id: int, confirm: bool) -> str:
    """
    Permanently delete a transaction and recompute the owning holding. If the
    transaction has a paired counterparty transaction (from add_transaction with
    counterparty_holding_id), that paired transaction is also deleted. Pass
    confirm=True to confirm; this cannot be undone.
    """
    try:
        if not confirm:
            return json.dumps({"ok": False, "error": "Pass confirm=True to confirm deletion"}, ensure_ascii=False)

        session = get_session()
        try:
            tx = session.get(Transaction, tx_id)
            if not tx:
                return json.dumps({"ok": False, "error": f"Transaction {tx_id} not found"}, ensure_ascii=False)

            affected_holdings = [session.get(Holding, tx.holding_id)]
            paired = find_paired_transaction(session, tx)
            paired_id = paired.id if paired else None
            if paired is not None:
                affected_holdings.append(session.get(Holding, paired.holding_id))
                session.delete(paired)
            session.delete(tx)
            session.flush()

            for h in affected_holdings:
                if h is not None:
                    recalculate_holding(session, h)
            session.commit()
            return json.dumps({
                "ok": True,
                "deleted_id": tx_id,
                "paired_deleted_id": paired_id,
            }, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tools — Price
# ---------------------------------------------------------------------------

@mcp.tool()
def refresh_prices() -> str:
    """
    Trigger a live price refresh for all holdings from market data sources
    (Tushare for A-shares, yfinance for US/JP/crypto). Also refreshes exchange rates.
    Holdings with manual price overrides are skipped. This may take 10-30 seconds.
    """
    try:
        fetch_exchange_rates()
        session = get_session()
        try:
            holdings = session.execute(select(Holding)).scalars().all()
            result = refresh_all_prices(holdings)
            return json.dumps(result, ensure_ascii=False, indent=2)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def set_price_override(
    symbol: str,
    price: float,
    currency: Literal["CNY", "USD", "JPY", "HKD", "EUR", "GBP"] = "CNY",
) -> str:
    """
    Manually set the price for a symbol, bypassing automatic fetching.
    Useful for illiquid assets or when the data source is unreliable.
    The override persists until cleared with clear_price_override.
    """
    try:
        symbol = symbol.strip().upper()
        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"}, ensure_ascii=False)
        if price <= 0:
            return json.dumps({"ok": False, "error": "price must be > 0"}, ensure_ascii=False)

        set_manual_price(symbol, price, currency)
        return json.dumps({"ok": True, "symbol": symbol, "price": price, "currency": currency}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def clear_price_override(symbol: str) -> str:
    """
    Remove the manual price override for a symbol, allowing automatic price fetching to resume
    on the next refresh_prices call.
    """
    try:
        symbol = symbol.strip().upper()
        if not symbol:
            return json.dumps({"ok": False, "error": "symbol is required"}, ensure_ascii=False)

        clear_manual_override(symbol)
        return json.dumps({"ok": True, "symbol": symbol}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def backfill_history() -> str:
    """
    Replay all dates in price_history and write portfolio_value_history snapshots
    (per-holding, per-tag, and total) for each date, using transaction-derived
    quantities at that point in time. Run after importing historical prices, or to
    repair the value-history series. Idempotent (upserts).
    """
    try:
        session = get_session()
        try:
            days = backfill_value_history(session)
            return json.dumps({"ok": True, "days_processed": days}, ensure_ascii=False)
        finally:
            session.close()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Bearer token auth middleware (streamable-http transport only)
# ---------------------------------------------------------------------------

class _BearerAuthMiddleware:
    """Pure-ASGI Bearer token middleware — does not buffer SSE/streaming responses."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], self.token):
                await self.app(scope, receive, send)
                return
            body = b'{"error":"Unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="mcp"'),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    transport = os.environ.get("TRANSPORT", "stdio")
    if transport == "streamable-http":
        logging.getLogger().setLevel(logging.INFO)
        mcp_token = os.environ.get("MCP_TOKEN", "").strip()
        starlette_app = mcp.streamable_http_app()
        if mcp_token:
            starlette_app.add_middleware(_BearerAuthMiddleware, token=mcp_token)
            logging.info("MCP Bearer token authentication enabled")
        else:
            logging.warning("MCP_TOKEN not set — MCP HTTP endpoint is unauthenticated")
        uvicorn.run(
            starlette_app,
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8000")),
            log_level="info",
        )
    else:
        mcp.run(transport="stdio")
