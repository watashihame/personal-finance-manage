import os

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import declarative_base, Session
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


def init_db():
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
