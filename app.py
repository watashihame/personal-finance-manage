import logging
import os
import secrets
from datetime import datetime, timezone, timedelta

from datetime import date as dt_date

from flask import Flask, request, redirect, url_for, jsonify, session
from sqlalchemy import select, func

from models import init_db, get_session, Holding, Transaction, PriceCache, ExchangeRate, PriceHistory, PortfolioValueHistory, recalculate_holding
from price_fetcher import (
    refresh_all_prices,
    set_manual_price,
    clear_manual_override,
    fetch_exchange_rates,
    compute_quantity_at_date,
    backfill_value_history,
    CHART_COLORS,
)

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "").strip()

init_db()

MARKETS = ["CN", "US", "JP", "CRYPTO", "OTHER"]
ASSET_TYPES = ["stock", "etf", "fund", "bond", "crypto", "cash", "other"]
CURRENCIES = ["CNY", "USD", "JPY", "HKD", "EUR", "GBP"]

MARKET_CURRENCY_DEFAULT = {
    "CN": "CNY",
    "US": "USD",
    "JP": "JPY",
    "CRYPTO": "USD",
    "OTHER": "CNY",
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_OPEN_ENDPOINTS = {"static", "spa_root", "api_auth_login", "api_auth_status"}

@app.before_request
def require_auth():
    if not ACCESS_TOKEN:
        return
    if request.endpoint in _OPEN_ENDPOINTS:
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], ACCESS_TOKEN):
        return
    if session.get("authenticated"):
        return
    if request.path.startswith("/api/"):
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for("spa_root"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_portfolio(holdings, prices: dict, rates: dict, prev_prices: dict) -> tuple[list[dict], float, float]:
    """
    Compute per-holding rows and totals.
    Returns (rows, total_value_cny, total_cost_cny).
    """
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

        prev_price = prev_prices.get(h.symbol) if not is_cash else None
        if current_price is not None and prev_price and prev_price > 0:
            daily_change_pct = (current_price - prev_price) / prev_price * 100
        else:
            daily_change_pct = None

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
            "market_value_cny": market_value_cny,
            "cost_cny": cost_cny,
            "pnl_cny": pnl_cny,
            "pnl_pct": pnl_pct,
            "daily_change_pct": daily_change_pct,
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


def _load_portfolio_data():
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

        today = dt_date.today()
        subq = (
            select(PriceHistory.symbol, func.max(PriceHistory.date).label("prev_date"))
            .where(PriceHistory.date < today)
            .group_by(PriceHistory.symbol)
            .subquery()
        )
        prev_rows = session.execute(
            select(PriceHistory.symbol, PriceHistory.price)
            .join(subq, (PriceHistory.symbol == subq.c.symbol) & (PriceHistory.date == subq.c.prev_date))
        ).all()
        prev_prices = {row.symbol: row.price for row in prev_rows}

        rows, total_value, total_cost = _compute_portfolio(holdings, price_map, rates, prev_prices)
        return rows, total_value, total_cost
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SPA entry point
# ---------------------------------------------------------------------------

@app.route("/")
def spa_root():
    return app.send_static_file("ui/Personal Finance.html")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/refresh-prices", methods=["POST"])
def api_refresh_prices():
    session = get_session()
    try:
        holdings = session.execute(select(Holding)).scalars().all()
        if not holdings:
            return jsonify({"updated": 0, "failed": 0, "errors": [], "timestamp": ""})
        # Also refresh exchange rates
        rates = fetch_exchange_rates()
        result = refresh_all_prices(holdings, rates=rates)
        return jsonify(result)
    finally:
        session.close()


@app.route("/api/override-price", methods=["POST"])
def api_override_price():
    data = request.get_json(force=True)
    symbol = str(data.get("symbol", "")).strip().upper()
    try:
        price = float(data["price"])
        currency = str(data.get("currency", "CNY")).upper()
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    if not symbol or price <= 0:
        return jsonify({"error": "无效的 symbol 或 price"}), 400

    set_manual_price(symbol, price, currency)
    return jsonify({"ok": True, "symbol": symbol, "price": price})


@app.route("/api/clear-override", methods=["POST"])
def api_clear_override():
    data = request.get_json(force=True)
    symbol = str(data.get("symbol", "")).strip().upper()
    if not symbol:
        return jsonify({"error": "缺少 symbol"}), 400
    clear_manual_override(symbol)
    return jsonify({"ok": True, "symbol": symbol})


@app.route("/api/portfolio-data")
def api_portfolio_data():
    rows, _, _ = _load_portfolio_data()
    rows_sorted = sorted(rows, key=lambda r: r["market_value_cny"], reverse=True)
    labels = [f"{r['name']} ({r['symbol']})" for r in rows_sorted]
    values = [round(r["market_value_cny"], 2) for r in rows_sorted]
    colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(rows_sorted))]
    return jsonify({"labels": labels, "values": values, "colors": colors})


@app.route("/api/price-history/<symbol>")
def api_price_history(symbol: str):
    symbol = symbol.upper()
    session_db = get_session()
    try:
        rows = session_db.execute(
            select(PriceHistory)
            .where(PriceHistory.symbol == symbol)
            .order_by(PriceHistory.date)
        ).scalars().all()
        return jsonify({
            "symbol": symbol,
            "dates": [r.date.isoformat() for r in rows],
            "prices": [r.price for r in rows],
            "currency": rows[-1].currency if rows else "",
        })
    finally:
        session_db.close()


@app.route("/api/portfolio-value-history")
def api_portfolio_value_history():
    db = get_session()
    try:
        rows = db.execute(
            select(PortfolioValueHistory)
            .where(PortfolioValueHistory.scope == "total")
            .order_by(PortfolioValueHistory.date)
        ).scalars().all()
        return jsonify({
            "dates":  [r.date.isoformat() for r in rows],
            "values": [r.value_cny for r in rows],
        })
    finally:
        db.close()


@app.route("/api/holding-value-history/<symbol>")
def api_holding_value_history(symbol: str):
    symbol = symbol.upper()
    db = get_session()
    try:
        rows = db.execute(
            select(PortfolioValueHistory)
            .where(
                PortfolioValueHistory.scope == symbol,
                PortfolioValueHistory.scope_type == "holding",
            )
            .order_by(PortfolioValueHistory.date)
        ).scalars().all()
        holding = db.execute(
            select(Holding).where(Holding.symbol == symbol)
        ).scalar_one_or_none()
        return jsonify({
            "symbol": symbol,
            "name": holding.name if holding else symbol,
            "dates":  [r.date.isoformat() for r in rows],
            "values": [r.value_cny for r in rows],
        })
    finally:
        db.close()


@app.route("/api/tag-value-history/<tag>")
def api_tag_value_history(tag: str):
    db = get_session()
    try:
        rows = db.execute(
            select(PortfolioValueHistory)
            .where(
                PortfolioValueHistory.scope == tag,
                PortfolioValueHistory.scope_type == "tag",
            )
            .order_by(PortfolioValueHistory.date)
        ).scalars().all()
        return jsonify({
            "tag":    tag,
            "dates":  [r.date.isoformat() for r in rows],
            "values": [r.value_cny for r in rows],
        })
    finally:
        db.close()


@app.route("/api/backfill-value-history", methods=["POST"])
def api_backfill_value_history():
    """遍历 price_history 中已有的历史日期，按当时持仓数量回填 portfolio_value_history。"""
    db = get_session()
    try:
        return jsonify({"days_processed": backfill_value_history(db)})
    finally:
        db.close()


@app.route("/api/holdings/search")
def api_holdings_search():
    q = request.args.get("q", "").strip().lower()
    session = get_session()
    try:
        holdings = session.execute(select(Holding)).scalars().all()
        results = []
        for h in holdings:
            if not q or q in h.name.lower() or q in h.symbol.lower():
                tag_list = [t.strip() for t in (h.tags or "").split(",") if t.strip()]
                results.append({
                    "id": h.id,
                    "name": h.name,
                    "symbol": h.symbol,
                    "market": h.market,
                    "quantity": h.quantity,
                    "tags": tag_list,
                })
        return jsonify(results)
    finally:
        session.close()


@app.route("/api/holdings", methods=["POST"])
def api_holding_add():
    data = request.get_json(force=True)
    required = ["name", "symbol", "market", "asset_type", "currency", "quantity", "cost_price"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"缺少必填字段: {field}"}), 400
    try:
        quantity = float(data["quantity"])
        cost_price = float(data["cost_price"])
    except (TypeError, ValueError):
        return jsonify({"error": "quantity 和 cost_price 必须为数字"}), 400

    market = str(data["market"]).upper()
    asset_type = str(data["asset_type"]).lower()
    currency = str(data["currency"]).upper()
    if market not in MARKETS:
        return jsonify({"error": f"market 无效，可选值: {MARKETS}"}), 400
    if asset_type not in ASSET_TYPES:
        return jsonify({"error": f"asset_type 无效，可选值: {ASSET_TYPES}"}), 400
    if currency not in CURRENCIES:
        return jsonify({"error": f"currency 无效，可选值: {CURRENCIES}"}), 400

    if asset_type == "cash":
        if quantity <= 0:
            return jsonify({"error": "现金数量必须大于 0"}), 400
    else:
        if quantity <= 0 or cost_price <= 0:
            return jsonify({"error": "quantity 和 cost_price 必须大于 0"}), 400

    raw_tags = data.get("tags", "")
    if isinstance(raw_tags, list):
        raw_tags = ",".join(raw_tags)
    tags = ",".join(t.strip() for t in raw_tags.split(",") if t.strip())

    h = Holding(
        name=str(data["name"]).strip(),
        symbol=str(data["symbol"]).strip().upper(),
        market=market,
        asset_type=asset_type,
        currency=currency,
        quantity=quantity,
        cost_price=cost_price,
        tags=tags,
        notes=str(data.get("notes", "")).strip(),
    )
    session = get_session()
    try:
        session.add(h)
        session.flush()
        tx = Transaction(
            holding_id=h.id,
            tx_type="BUY",
            tx_date=dt_date.today(),
            quantity=quantity,
            unit_price=cost_price,
            fee=0.0,
            notes="初始建仓",
        )
        session.add(tx)
        session.commit()
        return jsonify({"ok": True, "id": h.id, "name": h.name, "symbol": h.symbol})
    finally:
        session.close()


@app.route("/api/holdings/<int:holding_id>/quantity", methods=["PATCH"])
def api_holding_quantity(holding_id: int):
    data = request.get_json(force=True)
    session = get_session()
    try:
        h = session.get(Holding, holding_id)
        if h is None:
            return jsonify({"error": "持仓不存在"}), 404

        if "quantity" in data:
            try:
                new_qty = float(data["quantity"])
            except (TypeError, ValueError):
                return jsonify({"error": "quantity 必须为数字"}), 400
        elif "delta" in data:
            try:
                new_qty = h.quantity + float(data["delta"])
            except (TypeError, ValueError):
                return jsonify({"error": "delta 必须为数字"}), 400
        else:
            return jsonify({"error": "请提供 quantity 或 delta"}), 400

        if new_qty <= 0:
            return jsonify({"error": "修改后的持有量必须大于 0"}), 400

        h.quantity = new_qty
        h.updated_at = datetime.now(timezone.utc)
        session.commit()
        return jsonify({"ok": True, "id": h.id, "symbol": h.symbol, "quantity": h.quantity})
    finally:
        session.close()


@app.route("/api/holdings/<int:holding_id>/tags", methods=["PATCH"])
def api_holding_tags(holding_id: int):
    data = request.get_json(force=True)
    if "tags" not in data:
        return jsonify({"error": "缺少 tags 字段"}), 400

    raw_tags = data["tags"]
    if isinstance(raw_tags, list):
        raw_tags = ",".join(str(t) for t in raw_tags)
    elif not isinstance(raw_tags, str):
        return jsonify({"error": "tags 必须为字符串或数组"}), 400

    tag_list = [t.strip() for t in raw_tags.split(",") if t.strip()]

    session = get_session()
    try:
        h = session.get(Holding, holding_id)
        if h is None:
            return jsonify({"error": "持仓不存在"}), 404
        h.tags = ",".join(tag_list)
        h.updated_at = datetime.now(timezone.utc)
        session.commit()
        return jsonify({"ok": True, "id": h.id, "symbol": h.symbol, "tags": tag_list})
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SPA Auth API
# ---------------------------------------------------------------------------

@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    if not ACCESS_TOKEN:
        session["authenticated"] = True
        return jsonify({"ok": True})
    data = request.get_json(force=True)
    token = str(data.get("token", "")).strip()
    if secrets.compare_digest(token, ACCESS_TOKEN):
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Token 不正确"}), 401


@app.route("/api/auth/status")
def api_auth_status():
    requires_auth = bool(ACCESS_TOKEN)
    authenticated = not requires_auth or bool(session.get("authenticated"))
    return jsonify({"authenticated": authenticated, "requiresAuth": requires_auth})


# ---------------------------------------------------------------------------
# SPA Data API
# ---------------------------------------------------------------------------

@app.route("/api/holdings", methods=["GET"])
def api_holdings_list():
    rows, _, _ = _load_portfolio_data()
    db = get_session()
    try:
        cutoff = dt_date.today() - timedelta(days=60)
        spark_rows = db.execute(
            select(PriceHistory.symbol, PriceHistory.price)
            .where(PriceHistory.date >= cutoff)
            .order_by(PriceHistory.symbol, PriceHistory.date)
        ).all()
        spark_map: dict[str, list] = {}
        for sr in spark_rows:
            spark_map.setdefault(sr.symbol, []).append(sr.price)
        return jsonify([{
            "id": r["id"],
            "name": r["name"],
            "symbol": r["symbol"],
            "market": r["market"],
            "type": r["asset_type"],
            "currency": r["currency"],
            "quantity": r["quantity"],
            "costPrice": r["cost_price"],
            "currentPrice": r["current_price"],
            "daily": r["daily_change_pct"],
            "valueCny": r["market_value_cny"],
            "costCny": r["cost_cny"],
            "pnlCny": r["pnl_cny"],
            "pnlPct": r["pnl_pct"],
            "tags": r["tags"],
            "spark": spark_map.get(r["symbol"], []),
            "isManual": r["is_manual"],
            "priceStale": r["price_stale"],
        } for r in rows])
    finally:
        db.close()


@app.route("/api/holdings/<int:holding_id>", methods=["GET"])
def api_holding_detail(holding_id: int):
    rows, _, _ = _load_portfolio_data()
    r = next((x for x in rows if x["id"] == holding_id), None)
    if r is None:
        return jsonify({"error": "持仓不存在"}), 404
    db = get_session()
    try:
        txs = db.execute(
            select(Transaction)
            .where(Transaction.holding_id == holding_id)
            .order_by(Transaction.tx_date.desc(), Transaction.id.desc())
        ).scalars().all()
        cutoff = dt_date.today() - timedelta(days=60)
        spark = db.execute(
            select(PriceHistory.price)
            .where(PriceHistory.symbol == r["symbol"], PriceHistory.date >= cutoff)
            .order_by(PriceHistory.date)
        ).scalars().all()
        return jsonify({
            "id": r["id"], "name": r["name"], "symbol": r["symbol"],
            "market": r["market"], "type": r["asset_type"],
            "currency": r["currency"], "quantity": r["quantity"],
            "costPrice": r["cost_price"], "currentPrice": r["current_price"],
            "daily": r["daily_change_pct"], "valueCny": r["market_value_cny"],
            "costCny": r["cost_cny"], "pnlCny": r["pnl_cny"],
            "pnlPct": r["pnl_pct"], "tags": r["tags"],
            "spark": list(spark), "isManual": r["is_manual"],
            "priceStale": r["price_stale"],
            "transactions": [{
                "id": t.id, "holdingId": t.holding_id, "type": t.tx_type,
                "date": t.tx_date.isoformat(), "quantity": t.quantity,
                "unitPrice": t.unit_price, "fee": t.fee or 0.0, "notes": t.notes or "",
            } for t in txs],
        })
    finally:
        db.close()


@app.route("/api/holdings/<int:holding_id>", methods=["PATCH"])
def api_holding_update(holding_id: int):
    data = request.get_json(force=True)
    db = get_session()
    try:
        h = db.get(Holding, holding_id)
        if h is None:
            return jsonify({"error": "持仓不存在"}), 404
        if "name" in data:
            h.name = str(data["name"]).strip()
        if "tags" in data:
            raw = data["tags"]
            if isinstance(raw, list):
                raw = ",".join(str(t) for t in raw)
            h.tags = ",".join(t.strip() for t in raw.split(",") if t.strip())
        if "notes" in data:
            h.notes = str(data["notes"]).strip()
        h.updated_at = datetime.now(timezone.utc)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/holdings/<int:holding_id>/transactions", methods=["POST"])
def api_transaction_add(holding_id: int):
    db = get_session()
    try:
        h = db.get(Holding, holding_id)
        if h is None:
            return jsonify({"error": "持仓不存在"}), 404
        data = request.get_json(force=True)
        try:
            tx_type = str(data["type"]).upper()
            quantity = float(data["quantity"])
            unit_price = float(data["unitPrice"])
            fee = float(data.get("fee") or 0)
            notes = str(data.get("notes", "")).strip()
            counterparty_id = data.get("counterpartyHoldingId")
            counterparty_unit_price = data.get("counterpartyUnitPrice")

            tx = Transaction(
                holding_id=holding_id,
                tx_type=tx_type,
                tx_date=dt_date.fromisoformat(data["date"]),
                quantity=quantity,
                unit_price=unit_price,
                fee=fee,
                notes=notes,
            )
            db.add(tx)
            db.flush()

            # Create paired transaction on counterparty
            paired_tx = None
            if counterparty_id is not None:
                cparty = db.get(Holding, counterparty_id)
                if cparty is None:
                    return jsonify({"error": "对方持仓不存在"}), 404

                # Determine paired direction: BUY↔SELL
                if tx_type == "BUY":
                    paired_type = "SELL"
                elif tx_type == "SELL":
                    paired_type = "BUY"
                elif tx_type == "TRANSFER_IN":
                    paired_type = "TRANSFER_OUT"
                else:
                    paired_type = "TRANSFER_IN"

                # Calculate paired quantity
                if cparty.asset_type == "cash":
                    # Cash: quantity = value in cash units (unit_price=1)
                    if tx_type in ("BUY", "TRANSFER_IN"):
                        paired_qty = quantity * unit_price + fee
                    else:
                        paired_qty = quantity * unit_price - fee
                    paired_up = 1.0
                else:
                    # Non-cash conversion: user specifies counterparty price
                    paired_qty = quantity * unit_price
                    if tx_type in ("BUY", "TRANSFER_IN"):
                        paired_qty += fee
                    else:
                        paired_qty -= fee
                    if counterparty_unit_price:
                        paired_up = float(counterparty_unit_price)
                        paired_qty = paired_qty / paired_up
                    else:
                        paired_up = counterparty_unit_price  # will fail validation

                if paired_qty <= 0:
                    return jsonify({"error": f"对方交易数量必须大于0，当前计算值为{paired_qty}"}), 400
                if paired_up is None or paired_up <= 0:
                    return jsonify({"error": "转换为其他投资标的需要提供目标价格 (counterpartyUnitPrice)"}), 400

                paired_tx = Transaction(
                    holding_id=counterparty_id,
                    tx_type=paired_type,
                    tx_date=dt_date.fromisoformat(data["date"]),
                    quantity=paired_qty,
                    unit_price=paired_up,
                    fee=0.0,
                    notes=f"来自 {h.symbol} 的{'买入' if paired_type == 'BUY' else '卖出'}",
                )
                db.add(paired_tx)
                db.flush()

                # Link both transactions to each other
                tx.counterparty_id = counterparty_id
                paired_tx.counterparty_id = holding_id

            recalculate_holding(db, h)
            if paired_tx:
                recalculate_holding(db, cparty)
            db.commit()
            result = {"ok": True, "id": tx.id}
            if paired_tx:
                result["pairedTransactionId"] = paired_tx.id
            return jsonify(result)
        except (ValueError, KeyError) as exc:
            return jsonify({"error": str(exc)}), 400
    finally:
        db.close()


@app.route("/api/portfolio")
def api_portfolio():
    rows, total_value, total_cost = _load_portfolio_data()
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0
    day_pnl = sum(
        (r["daily_change_pct"] / 100) * r["market_value_cny"]
        for r in rows if r["daily_change_pct"] is not None
    )
    prev_total = total_value - day_pnl
    day_pnl_pct = (day_pnl / prev_total * 100) if prev_total else 0.0
    return jsonify({
        "totalValueCny": round(total_value, 2),
        "totalCostCny": round(total_cost, 2),
        "totalPnlCny": round(total_pnl, 2),
        "totalPnlPct": round(total_pnl_pct, 4),
        "dayPnl": round(day_pnl, 2),
        "dayPnlPct": round(day_pnl_pct, 4),
        "holdingsCount": len(rows),
    })


@app.route("/api/tags")
def api_tags():
    rows, total_value, _ = _load_portfolio_data()
    tag_totals: dict[str, float] = {}
    for r in rows:
        for tag in r["tags"]:
            tag_totals[tag] = tag_totals.get(tag, 0.0) + r["market_value_cny"]
    return jsonify([{
        "tag": tag,
        "valueCny": round(val, 2),
        "pct": round(val / total_value * 100, 2) if total_value else 0.0,
    } for tag, val in sorted(tag_totals.items(), key=lambda x: -x[1])])


@app.route("/api/exchange-rates")
def api_exchange_rates():
    db = get_session()
    try:
        rates = {r.from_currency: r.rate for r in db.execute(select(ExchangeRate)).scalars().all()}
        rates["CNY"] = 1.0
        return jsonify(rates)
    finally:
        db.close()


def _find_paired_transaction(db, tx: Transaction) -> Transaction | None:
    """Locate the paired transaction created alongside `tx` (counterparty side)."""
    if not tx.counterparty_id:
        return None
    opposite = {
        "BUY": "SELL", "SELL": "BUY",
        "TRANSFER_IN": "TRANSFER_OUT", "TRANSFER_OUT": "TRANSFER_IN",
    }.get(tx.tx_type)
    if not opposite:
        return None
    return db.execute(
        select(Transaction)
        .where(
            Transaction.holding_id == tx.counterparty_id,
            Transaction.counterparty_id == tx.holding_id,
            Transaction.tx_date == tx.tx_date,
            Transaction.tx_type == opposite,
            Transaction.id != tx.id,
        )
        .order_by(Transaction.id.desc())
    ).scalars().first()


@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
def api_transaction_delete(tx_id: int):
    db = get_session()
    try:
        tx = db.get(Transaction, tx_id)
        if tx is None:
            return jsonify({"error": "交易记录不存在"}), 404

        affected_holdings = [db.get(Holding, tx.holding_id)]
        paired = _find_paired_transaction(db, tx)
        if paired is not None:
            affected_holdings.append(db.get(Holding, paired.holding_id))
            db.delete(paired)
        db.delete(tx)
        db.flush()

        for h in affected_holdings:
            if h is not None:
                recalculate_holding(db, h)
        db.commit()
        return jsonify({
            "ok": True,
            "deletedId": tx_id,
            "pairedDeletedId": paired.id if paired else None,
        })
    finally:
        db.close()


@app.route("/api/transactions/<int:tx_id>", methods=["PATCH"])
def api_transaction_update(tx_id: int):
    data = request.get_json(force=True)
    db = get_session()
    try:
        tx = db.get(Transaction, tx_id)
        if tx is None:
            return jsonify({"error": "交易记录不存在"}), 404

        try:
            if "type" in data:
                t = str(data["type"]).upper()
                if t not in ("BUY", "SELL", "TRANSFER_IN", "TRANSFER_OUT"):
                    return jsonify({"error": f"无效的交易类型: {t}"}), 400
                tx.tx_type = t
            if "date" in data:
                tx.tx_date = dt_date.fromisoformat(str(data["date"]))
            if "quantity" in data:
                q = float(data["quantity"])
                if q <= 0:
                    return jsonify({"error": "数量必须大于 0"}), 400
                tx.quantity = q
            if "unitPrice" in data:
                up = float(data["unitPrice"])
                if up <= 0:
                    return jsonify({"error": "价格必须大于 0"}), 400
                tx.unit_price = up
            if "fee" in data:
                tx.fee = float(data["fee"] or 0)
            if "notes" in data:
                tx.notes = str(data["notes"]).strip()
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"参数无效: {exc}"}), 400

        db.flush()
        h = db.get(Holding, tx.holding_id)
        if h is not None:
            recalculate_holding(db, h)
        db.commit()
        return jsonify({
            "ok": True,
            "id": tx.id,
            "hasPaired": tx.counterparty_id is not None,
        })
    finally:
        db.close()


@app.route("/api/transactions")
def api_transactions():
    holding_id = request.args.get("holding_id", type=int)
    db = get_session()
    try:
        q = select(Transaction).order_by(Transaction.tx_date.desc(), Transaction.id.desc())
        if holding_id:
            q = q.where(Transaction.holding_id == holding_id)
        txs = db.execute(q).scalars().all()
        cp_ids = {t.counterparty_id for t in txs if t.counterparty_id}
        cp_map = {}
        if cp_ids:
            cp_holdings = db.execute(
                select(Holding).where(Holding.id.in_(cp_ids))
            ).scalars().all()
            cp_map = {h.id: h.symbol for h in cp_holdings}
        return jsonify([{
            "id": t.id, "holdingId": t.holding_id, "type": t.tx_type,
            "date": t.tx_date.isoformat(), "quantity": t.quantity,
            "unitPrice": t.unit_price, "fee": t.fee or 0.0, "notes": t.notes or "",
            "counterpartyId": t.counterparty_id,
            "counterpartySymbol": cp_map.get(t.counterparty_id) if t.counterparty_id else None,
        } for t in txs])
    finally:
        db.close()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
