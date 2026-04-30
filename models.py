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
