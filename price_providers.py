"""Pluggable price-data providers.

Every provider exposes the same contract::

    fetch(symbols: list[str]) -> dict[str, float | None]

returning a price in the holding's *native* currency per symbol, or ``None``
when unavailable. Providers are grouped into per-market priority chains in
``CHAINS``; :func:`fetch_bucket` walks a chain and passes the symbols a provider
could not resolve on to the next one (per-symbol fallback).

Heavy third-party libraries (yfinance / tushare / akshare / bs4) are imported
lazily inside each fetcher, so this module imports cleanly even when an optional
dependency is missing — that source simply returns ``None`` and the chain falls
back to the next provider.
"""

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

JP_BARE_CODE_RE = re.compile(r'^(?:\d{4}|\d{3}[A-Z])$', re.IGNORECASE)

ICBC_GOLD_URL = "https://mybank.icbc.com.cn/icbc/newperbank/perbank3/gold/goldaccrual_query_out.jsp"
ICBC_GOLD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://mybank.icbc.com.cn/",
}
YAHOO_CHART_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
_EASTMONEY_HEADERS = {"Referer": "https://fundf10.eastmoney.com/"}
_EASTMONEY_URL = "https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=1"
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


# ---------------------------------------------------------------------------
# Symbol classification
# ---------------------------------------------------------------------------

def is_ashare(symbol: str) -> bool:
    return symbol.upper().endswith((".SH", ".SZ"))


def is_japanese(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    return normalized.endswith((".T", ".JP")) or bool(JP_BARE_CODE_RE.match(normalized))


def is_crypto(symbol: str) -> bool:
    upper = symbol.upper()
    return "-USD" in upper or "-USDT" in upper


def is_cn_fund(symbol: str) -> bool:
    """六位数字（含或不含 .OF 后缀）= A 股开放式（场外）基金。"""
    return bool(re.match(r'^\d{6}(\.OF)?$', symbol, re.IGNORECASE))


def is_icbc_gold(symbol: str) -> bool:
    return symbol.upper() == "ICBC-GOLD"


# 比 market 更细的分桶；每个 bucket 对应一条 provider 回退链。
def classify_bucket(symbol: str) -> str:
    if is_ashare(symbol):
        return "ashare"
    if is_cn_fund(symbol):
        return "cn_fund"
    if is_icbc_gold(symbol):
        return "icbc_gold"
    if is_japanese(symbol):
        return "jp"
    if is_crypto(symbol):
        return "crypto"
    return "us"


BUCKET_MARKET = {
    "ashare": "cn",
    "cn_fund": "cn",
    "icbc_gold": "cn",
    "jp": "jp",
    "us": "us",
    "crypto": "crypto",
}

MARKETS = ("all", "cn", "us", "jp", "crypto")


def classify_market(symbol: str) -> str:
    """A股/场外基金/ICBC黄金归为 cn；日股 jp；加密 crypto；其余 us。"""
    return BUCKET_MARKET[classify_bucket(symbol)]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_float(value) -> float | None:
    """Coerce to a positive float; treat None / NaN / non-numeric / <=0 as missing."""
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result if result > 0 else None


def _http_get(url: str, *, retries: int = 2, backoff: float = 0.5, **kwargs) -> requests.Response:
    """GET with raise_for_status and exponential-backoff retry. Re-raises the last error.

    4xx responses (except 429) are deterministic — they are not retried.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            last_exc = exc
            code = exc.response.status_code if exc.response is not None else None
            if code is not None and 400 <= code < 500 and code != 429:
                break  # client error, retrying won't help
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
        except Exception as exc:  # noqa: BLE001 — retry any other transient error
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


def _load_tushare_token() -> str | None:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token or token == "your_tushare_token_here":
        return None
    return token


def _load_finnhub_key() -> str | None:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key or key == "your_finnhub_key_here":
        return None
    return key


def _proxies() -> dict | None:
    """Optional SOCKS5/HTTP proxy for the Yahoo sources, from `PRICE_PROXY`.

    Yahoo aggressively blocks datacenter IPs; routing through a clean (e.g.
    residential) egress fixes the resulting flakiness. Use `socks5h://host:port`
    so DNS is resolved through the proxy too. Requires `requests[socks]`.
    Returns a requests-style proxies dict, or None when unset.
    """
    proxy = os.environ.get("PRICE_PROXY", "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def to_yahoo_jp_symbol(sym: str) -> str:
    """Normalize a JP symbol (`7203`, `7203.T`, `200A.JP`) to Yahoo's `<code>.T` form."""
    lookup = re.sub(r'\.JP$', '.T', sym.strip(), flags=re.IGNORECASE)
    if JP_BARE_CODE_RE.match(lookup):
        lookup = f"{lookup.upper()}.T"
    return lookup.upper()


def to_yahoo_symbol(sym: str) -> str:
    """Map any holding symbol to Yahoo's quote symbol: JP -> `<code>.T`,
    crypto -> `<base>-USD` (Yahoo uses USD pairs, not USDT), US -> ticker as-is."""
    if is_japanese(sym):
        return to_yahoo_jp_symbol(sym)
    if is_crypto(sym):
        return re.sub(r'-USDT$', '-USD', sym.strip(), flags=re.IGNORECASE).upper()
    return sym.strip().upper()


def _extract_chart_price(data: dict) -> float | None:
    results = data.get("chart", {}).get("result") or []
    if not results:
        return None
    result = results[0]
    price = result.get("meta", {}).get("regularMarketPrice")
    if price is None:
        quotes = result.get("indicators", {}).get("quote") or []
        closes = quotes[0].get("close", []) if quotes else []
        price = next((p for p in reversed(closes) if p is not None), None)
    return _safe_float(price)


class _LegacySSLAdapter(requests.adapters.HTTPAdapter):
    """Allow legacy TLS renegotiation for older bank servers (e.g., ICBC)."""

    def init_poolmanager(self, *args, **kwargs):
        import ssl
        ctx = ssl.create_default_context()
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


# ---------------------------------------------------------------------------
# A-share: Tushare (primary) -> akshare (fallback, token-free)
# ---------------------------------------------------------------------------

def fetch_tushare(symbols: list[str]) -> dict[str, float | None]:
    token = _load_tushare_token()
    if not token:
        logger.warning("Tushare token not configured")
        return {s: None for s in symbols}
    try:
        import tushare as ts
        pro = ts.pro_api(token)
        df = pro.daily(ts_code=",".join(symbols), limit=len(symbols))
        if df is None or df.empty:
            return {s: None for s in symbols}
        df = df.sort_values("trade_date", ascending=False).drop_duplicates(subset="ts_code", keep="first")
        price_map = dict(zip(df["ts_code"], df["close"]))
        return {sym: _safe_float(price_map.get(sym)) for sym in symbols}
    except Exception as exc:
        logger.error("Tushare fetch failed: %s", exc)
        return {s: None for s in symbols}


def fetch_akshare_ashare(symbols: list[str]) -> dict[str, float | None]:
    """A股实时快照（东方财富，免 token）。按 6 位代码匹配最新价。"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        price_map = {str(code): price for code, price in zip(df["代码"].astype(str), df["最新价"])}
    except Exception as exc:
        logger.warning("akshare A-share spot failed: %s", exc)
        return {s: None for s in symbols}
    out: dict[str, float | None] = {}
    for sym in symbols:
        code = re.sub(r'\.(SH|SZ)$', '', sym, flags=re.IGNORECASE)
        out[sym] = _safe_float(price_map.get(code))
    return out


# ---------------------------------------------------------------------------
# CN open-end fund NAV: 天天基金 (primary) -> akshare (fallback)
# ---------------------------------------------------------------------------

def _fetch_one_eastmoney(sym: str) -> tuple[str, float | None]:
    code = re.sub(r'\.OF$', '', sym, flags=re.IGNORECASE)
    try:
        resp = _http_get(
            _EASTMONEY_URL.format(code=code),
            headers=_EASTMONEY_HEADERS, timeout=20, retries=2, backoff=0.5,
        )
        lst = resp.json().get("Data", {}).get("LSJZList", [])
        return sym, (_safe_float(lst[0]["DWJZ"]) if lst else None)
    except Exception as exc:
        logger.warning("eastmoney fund_nav failed for %s: %s", sym, exc)
        return sym, None


def fetch_eastmoney_fund(symbols: list[str]) -> dict[str, float | None]:
    """Fetch unit NAV (单位净值) from 天天基金 concurrently for each fund symbol."""
    results: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as pool:
        futures = {pool.submit(_fetch_one_eastmoney, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, price = future.result()
            results[sym] = price
    return results


def _fetch_one_akshare_fund(code: str) -> float | None:
    import akshare as ak
    # akshare 不同版本参数名在 fund/ symbol 间变动，两种都试。
    for kwargs in ({"symbol": code, "indicator": "单位净值走势"},
                   {"fund": code, "indicator": "单位净值走势"}):
        try:
            df = ak.fund_open_fund_info_em(**kwargs)
        except TypeError:
            continue
        except Exception as exc:
            logger.warning("akshare fund nav failed for %s: %s", code, exc)
            return None
        if df is None or len(df) == 0:
            return None
        try:
            return _safe_float(df["单位净值"].iloc[-1])
        except Exception:
            return None
    return None


def fetch_akshare_fund(symbols: list[str]) -> dict[str, float | None]:
    try:
        import akshare  # noqa: F401 — availability probe
    except Exception as exc:
        logger.warning("akshare not available for fund NAV: %s", exc)
        return {s: None for s in symbols}
    results: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 4)) as pool:
        futures = {
            pool.submit(_fetch_one_akshare_fund, re.sub(r'\.OF$', '', sym, flags=re.IGNORECASE)): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                results[sym] = future.result()
            except Exception:
                results[sym] = None
    return results


# ---------------------------------------------------------------------------
# ICBC gold accumulation (工银积存金) price scraper
# ---------------------------------------------------------------------------

def fetch_icbc_gold(symbols: list[str]) -> dict[str, float | None]:
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
            candidate = _safe_float(tag.get_text(strip=True))
            if candidate is not None and 300 < candidate < 3000:
                price = candidate

        # 策略2：全文正则回退 — id="activeprice_..." 后跟数字
        if price is None:
            m = re.search(r'id="activeprice_[^"]*"[^>]*>(\d{3,4}\.\d{2})', resp.text)
            if m:
                candidate = _safe_float(m.group(1))
                if candidate is not None and 300 < candidate < 3000:
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
# Yahoo (US / JP / crypto): the raw chart API via requests (primary, proxy-aware
# through PRICE_PROXY) -> the yfinance library (fallback). The raw chart API is
# more stable than the yfinance lib and gives full control over proxying, which
# the yfinance lib's curl_cffi backend does not do reliably.
# ---------------------------------------------------------------------------

def _fetch_one_yahoo_chart(sym: str) -> tuple[str, float | None]:
    lookup_sym = to_yahoo_symbol(sym)
    proxies = _proxies()
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            resp = _http_get(
                f"https://{host}/v8/finance/chart/{quote(lookup_sym)}",
                params={"interval": "1d", "range": "5d"},
                headers=YAHOO_CHART_HEADERS, timeout=12, retries=1, backoff=0.5,
                proxies=proxies,
            )
            price = _extract_chart_price(resp.json())
            if price is not None:
                return sym, price
        except Exception as exc:
            logger.warning("Yahoo chart failed for %s via %s: %s", sym, host, exc)
    return sym, None


def fetch_yahoo_chart(symbols: list[str]) -> dict[str, float | None]:
    if not symbols:
        return {}
    results: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 4)) as pool:
        futures = {pool.submit(_fetch_one_yahoo_chart, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, price = future.result()
            results[sym] = price
    return results


def _fetch_one_yfinance(sym: str) -> tuple[str, float | None]:
    try:
        import yfinance as yf
        lookup_sym = to_yahoo_symbol(sym)
        proxies = _proxies()
        if proxies:
            # best-effort proxying of the yfinance lib; if PRICE_PROXY is set we
            # only go through it (no direct fallback) to keep the egress clean.
            sess = requests.Session()
            sess.proxies.update(proxies)
            ticker = yf.Ticker(lookup_sym, session=sess)
        else:
            ticker = yf.Ticker(lookup_sym)
        return sym, _safe_float(ticker.fast_info.last_price)
    except Exception as exc:
        logger.warning("yfinance failed for %s: %s", sym, exc)
        return sym, None


def fetch_yfinance(symbols: list[str]) -> dict[str, float | None]:
    if not symbols:
        return {}
    results: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as pool:
        futures = {pool.submit(_fetch_one_yfinance, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, price = future.result()
            results[sym] = price
    return results


# ---------------------------------------------------------------------------
# Finnhub: real-time US stocks + crypto (free tier; key via FINNHUB_API_KEY).
# Free tier has NO access to JP / A-share / HK quotes (returns 403), so this
# provider is only wired into the US and crypto chains.
# ---------------------------------------------------------------------------

def _to_finnhub_symbol(sym: str) -> str:
    """US tickers pass through; crypto maps to Binance pairs, e.g. BTC-USD -> BINANCE:BTCUSDT."""
    if is_crypto(sym):
        base = re.split(r'[-/]', sym.strip(), maxsplit=1)[0].upper()
        return f"BINANCE:{base}USDT"
    return sym.strip().upper()


def _fetch_one_finnhub(sym: str, key: str) -> tuple[str, float | None]:
    fin_sym = _to_finnhub_symbol(sym)
    try:
        resp = _http_get(
            FINNHUB_QUOTE_URL,
            params={"symbol": fin_sym, "token": key},
            timeout=10, retries=2, backoff=0.5,
        )
        # /quote returns {"c": current, "pc": prev_close, ...}; c==0 means no data.
        return sym, _safe_float(resp.json().get("c"))
    except Exception as exc:
        logger.warning("finnhub failed for %s (%s): %s", sym, fin_sym, exc)
        return sym, None


def fetch_finnhub(symbols: list[str]) -> dict[str, float | None]:
    key = _load_finnhub_key()
    if not key:
        logger.info("Finnhub API key not configured; skipping finnhub provider")
        return {s: None for s in symbols}
    results: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as pool:
        futures = {pool.submit(_fetch_one_finnhub, sym, key): sym for sym in symbols}
        for future in as_completed(futures):
            sym, price = future.result()
            results[sym] = price
    return results


# ---------------------------------------------------------------------------
# Provider chains
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    name: str
    fetch: Callable[[list[str]], dict[str, float | None]]


CHAINS: dict[str, list[Provider]] = {
    "ashare":    [Provider("tushare", fetch_tushare), Provider("akshare-a", fetch_akshare_ashare)],
    "cn_fund":   [Provider("eastmoney", fetch_eastmoney_fund), Provider("akshare-fund", fetch_akshare_fund)],
    "icbc_gold": [Provider("icbc", fetch_icbc_gold)],
    "jp":        [Provider("yahoo-chart", fetch_yahoo_chart), Provider("yfinance", fetch_yfinance)],
    "us":        [Provider("finnhub", fetch_finnhub), Provider("yahoo-chart", fetch_yahoo_chart), Provider("yfinance", fetch_yfinance)],
    "crypto":    [Provider("finnhub", fetch_finnhub), Provider("yahoo-chart", fetch_yahoo_chart), Provider("yfinance", fetch_yfinance)],
}


def fetch_bucket(bucket: str, symbols: list[str]) -> dict[str, tuple[float | None, str | None]]:
    """Run ``bucket``'s provider chain with per-symbol fallback.

    Returns ``{symbol: (price_or_None, source_name_or_None)}``. Each provider only
    receives the symbols still unresolved by the previous ones.
    """
    resolved: dict[str, tuple[float | None, str | None]] = {s: (None, None) for s in symbols}
    pending = list(symbols)
    for provider in CHAINS.get(bucket, []):
        if not pending:
            break
        try:
            res = provider.fetch(pending)
        except Exception as exc:
            logger.error("provider %s failed (bucket %s): %s", provider.name, bucket, exc)
            continue
        still_pending: list[str] = []
        for sym in pending:
            price = res.get(sym)
            if price is not None:
                resolved[sym] = (price, provider.name)
            else:
                still_pending.append(sym)
        pending = still_pending
    return resolved
