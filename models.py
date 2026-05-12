import os

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Date, UniqueConstraint, ForeignKey
from sqlalchemy.orm import declarative_base, Session, relationship
from datetime import datetime, timezone

Base = declarative_base()

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///portfolio.db",  # local fallback for development
)
engine = create_engine(_DATABASE_URL, echo=False)


class Holding(Base):
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(30), nullable=False)
    market = Column(String(10), nullable=False)      # US / CN / JP / CRYPTO / OTHER
    asset_type = Column(String(10), nullable=False)  # stock / etf / fund / bond / crypto
    currency = Column(String(5), nullable=False)     # USD / CNY / JPY
    quantity = Column(Float, nullable=False)
    cost_price = Column(Float, nullable=False)
    tags = Column(String(200), default="")   # 逗号分隔，如 "科技,长期持有"
    notes = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    transactions = relationship("Transaction", back_populates="holding", order_by="Transaction.tx_date", cascade="all, delete-orphan", foreign_keys="[Transaction.holding_id]")


class Transaction(Base):
    """每一笔买入/卖出/转换交易记录。holdings 的 quantity 和 cost_price 由此汇总得出。"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    # BUY / SELL / TRANSFER_IN / TRANSFER_OUT
    tx_type = Column(String(15), nullable=False)
    tx_date = Column(Date, nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    counterparty_id = Column(Integer, ForeignKey("holdings.id"), nullable=True)
    notes = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    holding = relationship("Holding", back_populates="transactions", foreign_keys=[holding_id])


class PriceCache(Base):
    __tablename__ = "price_cache"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), unique=True, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(5), nullable=False)
    source = Column(String(20), default="yfinance")
    fetched_at = Column(DateTime, nullable=False)
    is_manual = Column(Boolean, default=False)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id = Column(Integer, primary_key=True)
    from_currency = Column(String(5), nullable=False)
    to_currency = Column(String(5), nullable=False, default="CNY")
    rate = Column(Float, nullable=False)
    fetched_at = Column(DateTime, nullable=False)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(30), nullable=False)
    date = Column(Date, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(5), nullable=False)
    source = Column(String(20), default="auto")
    __table_args__ = (UniqueConstraint('symbol', 'date', name='uq_ph_symbol_date'),)


class PortfolioValueHistory(Base):
    __tablename__ = "portfolio_value_history"

    id         = Column(Integer, primary_key=True)
    date       = Column(Date, nullable=False)
    scope      = Column(String(100), nullable=False)  # "total" | symbol | tag 名
    scope_type = Column(String(10),  nullable=False)  # "total" | "holding" | "tag"
    value_cny  = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint('date', 'scope', name='uq_pvh_date_scope'),)


def recalculate_holding(session, h) -> None:
    """从所有交易记录重新计算 holding.quantity 和 cost_price（加权平均成本法）。"""
    from sqlalchemy import select as sa_select
    txs = session.execute(
        sa_select(Transaction)
        .where(Transaction.holding_id == h.id)
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

    h.quantity = max(total_qty, 0.0)
    if total_qty > 0:
        h.cost_price = total_cost / total_qty


# ----------------------------------------------------------------------------
# 配对交易（counterparty）共享逻辑 —— app.py 和 mcp_server.py 都使用
# ----------------------------------------------------------------------------

_PAIR_OPPOSITE = {
    "BUY": "SELL",
    "SELL": "BUY",
    "TRANSFER_IN": "TRANSFER_OUT",
    "TRANSFER_OUT": "TRANSFER_IN",
}

_PAIR_TYPE_ZH = {"BUY": "买入", "SELL": "卖出", "TRANSFER_IN": "转入", "TRANSFER_OUT": "转出"}


def find_paired_transaction(session, tx) -> "Transaction | None":
    """通过 counterparty_id 双向互链定位 tx 的配对腿。

    注意：不按 tx_date / tx_type 过滤 —— 这样 PATCH 改了本侧字段后仍能找到对方。
    """
    if not tx.counterparty_id:
        return None
    from sqlalchemy import select as sa_select
    return session.execute(
        sa_select(Transaction).where(
            Transaction.holding_id == tx.counterparty_id,
            Transaction.counterparty_id == tx.holding_id,
            Transaction.id != tx.id,
        ).order_by(Transaction.id.desc())
    ).scalars().first()


def _calc_paired_qty_price(tx, cparty, cp_unit_price):
    """根据 tx 当前字段和对方 holding 类型，算出配对腿的 quantity / unit_price。"""
    base = tx.quantity * tx.unit_price
    if tx.tx_type in ("BUY", "TRANSFER_IN"):
        base += (tx.fee or 0.0)
    else:
        base -= (tx.fee or 0.0)

    if cparty.asset_type == "cash":
        return base, 1.0

    if not cp_unit_price or cp_unit_price <= 0:
        raise ValueError("非现金对方需提供 counterpartyUnitPrice")
    return base / cp_unit_price, float(cp_unit_price)


def create_paired_transaction(session, tx, cparty, cp_unit_price):
    """为 tx 创建一笔配对腿，互链 counterparty_id 并返回 paired tx。"""
    paired_type = _PAIR_OPPOSITE.get(tx.tx_type)
    if paired_type is None:
        raise ValueError(f"无效的交易类型: {tx.tx_type}")

    paired_qty, paired_up = _calc_paired_qty_price(tx, cparty, cp_unit_price)
    if paired_qty <= 0:
        raise ValueError(f"对方交易数量必须大于 0，当前计算值为 {paired_qty:.6f}")

    holding = session.get(Holding, tx.holding_id)
    paired = Transaction(
        holding_id=cparty.id,
        tx_type=paired_type,
        tx_date=tx.tx_date,
        quantity=paired_qty,
        unit_price=paired_up,
        fee=0.0,
        notes=f"来自 {holding.symbol} 的{_PAIR_TYPE_ZH.get(paired_type, '')}",
    )
    session.add(paired)
    session.flush()
    tx.counterparty_id = cparty.id
    paired.counterparty_id = tx.holding_id
    return paired


def apply_counterparty(session, tx, new_cp_id, new_cp_unit_price):
    """根据 new_cp_id 调整 tx 的配对关系。

    new_cp_id 语义：
      - None : 未传入此字段，保持现状（不动配对腿）。
      - 0    : 显式解除配对（删除现有配对腿，清空 tx.counterparty_id）。
      - >0   : 设置 / 更换为该 holding 作为对方：
               * 当前无配对           → 创建新配对腿
               * 当前配对到同一 holding → 同步配对腿的 type/date/quantity/unit_price
               * 当前配对到不同 holding → 删旧建新

    返回 (受影响的 holding 列表, 当前 paired tx 或 None)。
    caller 应对返回的 holdings 调用 recalculate_holding。
    """
    if new_cp_id is None:
        return [], find_paired_transaction(session, tx)

    current_paired = find_paired_transaction(session, tx)

    if new_cp_id == 0:
        if current_paired is None:
            tx.counterparty_id = None
            return [], None
        cp_holding = session.get(Holding, current_paired.holding_id)
        session.delete(current_paired)
        tx.counterparty_id = None
        return ([cp_holding] if cp_holding else []), None

    new_cp = session.get(Holding, new_cp_id)
    if new_cp is None:
        raise ValueError(f"对方持仓 {new_cp_id} 不存在")
    if new_cp.id == tx.holding_id:
        raise ValueError("对方不能是自身")

    if current_paired is not None and current_paired.holding_id == new_cp.id:
        paired_type = _PAIR_OPPOSITE.get(tx.tx_type)
        if paired_type is None:
            raise ValueError(f"无效的交易类型: {tx.tx_type}")
        cp_price = new_cp_unit_price
        if (not cp_price or cp_price <= 0) and new_cp.asset_type != "cash":
            cp_price = current_paired.unit_price
        paired_qty, paired_up = _calc_paired_qty_price(tx, new_cp, cp_price)
        if paired_qty <= 0:
            raise ValueError(f"对方交易数量必须大于 0，当前计算值为 {paired_qty:.6f}")
        current_paired.tx_type = paired_type
        current_paired.tx_date = tx.tx_date
        current_paired.quantity = paired_qty
        current_paired.unit_price = paired_up
        session.flush()
        return [new_cp], current_paired

    affected = []
    if current_paired is not None:
        old_cp_holding = session.get(Holding, current_paired.holding_id)
        session.delete(current_paired)
        if old_cp_holding is not None:
            affected.append(old_cp_holding)
        tx.counterparty_id = None
        session.flush()

    paired = create_paired_transaction(session, tx, new_cp, new_cp_unit_price)
    affected.append(new_cp)
    return affected, paired


def init_db():
    Base.metadata.create_all(engine)
    # Migration: add counterparty_id if missing (added 2026-05)
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    if "transactions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("transactions")}
        if "counterparty_id" not in cols:
            try:
                with engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE transactions ADD COLUMN counterparty_id INTEGER REFERENCES holdings(id)"
                    ))
                    conn.commit()
            except Exception:
                pass  # race between gunicorn workers


def get_session() -> Session:
    return Session(engine)
