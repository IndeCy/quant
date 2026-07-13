"""主线链动策略 Tushare 历史行情回填。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import time
from typing import Protocol

import pandas as pd

from backtest.cache import MarketDataCache
from examples.compare_chain_stock_selection import build_default_chain_definitions
from runtime.config import get_config_value
from runtime.paths import RuntimePaths, get_runtime_paths


PROVIDER = "tushare"
FREQUENCY = "1d"
ADJUST_QFQ = "qfq"
ADJUST_NONE = "none"
BENCHMARK_SYMBOL = "000001.SH"
MARKET_COLUMNS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]
FACTOR_COLUMNS = ["ts_code", "trade_date", "adj_factor"]


class MainlineTushareClient(Protocol):
    """主线回填所需的最小 Tushare 接口。"""

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def fund_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def fund_adj(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame: ...


class TushareBackfillProClient:
    """Tushare SDK 薄封装，便于测试替换。"""

    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(MARKET_COLUMNS))

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.adj_factor(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(FACTOR_COLUMNS))

    def fund_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(MARKET_COLUMNS))

    def fund_adj(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.fund_adj(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(FACTOR_COLUMNS))

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(MARKET_COLUMNS))


@dataclass(frozen=True)
class MainlineBackfillResult:
    """主线链动历史回填摘要。"""

    start_date: str
    end_date: str
    stock_symbols: int
    fund_symbols: int
    index_symbols: int
    rows_written: int
    missing_symbols: tuple[str, ...]


def backfill_mainline_tushare_cache(
    paths: RuntimePaths | None = None,
    client: MainlineTushareClient | None = None,
    start_date: str = "20210101",
    end_date: str | None = None,
    sleep_seconds: float = 0.25,
) -> MainlineBackfillResult:
    """回填主线链动股票池、代理 ETF 和上证基准到标准本地缓存。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    end = end_date or datetime.now().strftime("%Y%m%d")
    client = client or TushareBackfillProClient(get_config_value("TUSHARE_TOKEN"))
    chains = build_default_chain_definitions()
    stock_symbols = sorted({stock.symbol for chain in chains for stock in chain.stocks})
    fund_symbols = sorted({chain.proxy_symbol for chain in chains})
    cache = MarketDataCache(runtime_paths.data_dir / "market_cache.sqlite3")
    missing: list[str] = []
    rows_written = 0
    try:
        for symbol in stock_symbols:
            rows_written += _backfill_adjusted_symbol(
                cache,
                symbol,
                client.daily(symbol, start_date, end),
                client.adj_factor(symbol, start_date, end),
                missing,
            )
            time.sleep(sleep_seconds)
        for symbol in fund_symbols:
            rows_written += _backfill_adjusted_symbol(
                cache,
                symbol,
                client.fund_daily(symbol, start_date, end),
                client.fund_adj(symbol, start_date, end),
                missing,
            )
            time.sleep(sleep_seconds)
        rows_written += _backfill_index_symbol(
            cache,
            BENCHMARK_SYMBOL,
            client.index_daily(BENCHMARK_SYMBOL, start_date, end),
            missing,
        )
    finally:
        cache.close()
    return MainlineBackfillResult(
        start_date=start_date,
        end_date=end,
        stock_symbols=len(stock_symbols),
        fund_symbols=len(fund_symbols),
        index_symbols=1,
        rows_written=rows_written,
        missing_symbols=tuple(sorted(set(missing))),
    )


def _backfill_adjusted_symbol(
    cache: MarketDataCache,
    symbol: str,
    daily: pd.DataFrame,
    factors: pd.DataFrame,
    missing: list[str],
) -> int:
    frame = _join_daily_and_factor(symbol, daily, factors)
    if frame.empty:
        missing.append(symbol)
        return 0
    raw = _to_cache_bars(frame)
    qfq = _to_qfq_bars(frame)
    return _write(cache, symbol, ADJUST_NONE, raw) + _write(cache, symbol, ADJUST_QFQ, qfq)


def _backfill_index_symbol(cache: MarketDataCache, symbol: str, daily: pd.DataFrame, missing: list[str]) -> int:
    frame = _clean_market_frame(symbol, daily)
    if frame.empty:
        missing.append(symbol)
        return 0
    return _write(cache, symbol, ADJUST_NONE, _to_cache_bars(frame))


def _join_daily_and_factor(symbol: str, daily: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    market = _clean_market_frame(symbol, daily)
    factor_frame = _clean_factor_frame(symbol, factors)
    if market.empty or factor_frame.empty:
        return pd.DataFrame()
    return market.merge(factor_frame, on=["ts_code", "trade_date"], how="inner").sort_values("trade_date")


def _clean_market_frame(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=MARKET_COLUMNS)
    missing = [column for column in MARKET_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{symbol} 日线缺少字段: {missing}")
    result = frame[MARKET_COLUMNS].copy()
    result["ts_code"] = result["ts_code"].astype(str)
    result["trade_date"] = result["trade_date"].astype(str)
    return result[result["ts_code"].eq(symbol)].drop_duplicates(["ts_code", "trade_date"], keep="last")


def _clean_factor_frame(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=FACTOR_COLUMNS)
    missing = [column for column in FACTOR_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{symbol} 复权因子缺少字段: {missing}")
    result = frame[FACTOR_COLUMNS].copy()
    result["ts_code"] = result["ts_code"].astype(str)
    result["trade_date"] = result["trade_date"].astype(str)
    return result[result["ts_code"].eq(symbol)].drop_duplicates(["ts_code", "trade_date"], keep="last")


def _to_cache_bars(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d")
    result = result.set_index("trade_date").sort_index()
    result["volume"] = result["vol"].astype(float)
    return result[["open", "high", "low", "close", "volume", "amount"]]


def _to_qfq_bars(frame: pd.DataFrame) -> pd.DataFrame:
    raw = _to_cache_bars(frame)
    factors = frame.copy()
    factors["trade_date"] = pd.to_datetime(factors["trade_date"], format="%Y%m%d")
    factors = factors.set_index("trade_date").sort_index()["adj_factor"].astype(float)
    latest_factor = float(factors.iloc[-1])
    if latest_factor <= 0:
        raise ValueError("最新复权因子必须大于0")
    qfq = raw.copy()
    for column in ["open", "high", "low", "close"]:
        qfq[column] = raw[column].astype(float) * factors / latest_factor
    return qfq


def _write(cache: MarketDataCache, symbol: str, adjust: str, bars: pd.DataFrame) -> int:
    if bars.empty:
        return 0
    cache.upsert_bars(PROVIDER, symbol, FREQUENCY, adjust, bars)
    cache.record_coverage(PROVIDER, symbol, FREQUENCY, adjust, _date(bars.index.min()), _date(bars.index.max()))
    return len(bars)


def _date(value: object) -> date:
    return pd.Timestamp(value).date()
