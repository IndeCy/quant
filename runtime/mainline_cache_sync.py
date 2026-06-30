"""主线链动策略的增量行情缓存同步。

每日数据更新已经把 Tushare 增量写入 DuckDB；主线链动旧观察链路仍读取
market_cache.sqlite3。这里负责把两者打通，避免策略任务成功但观察日期滞后。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from backtest.cache import MarketDataCache
from backtest.mainline_observer import WARMUP_DAYS
from backtest.paper_trading import PaperTradingStore
from examples.compare_chain_stock_selection import (
    ADJUST as STOCK_ADJUST,
    FREQUENCY as STOCK_FREQUENCY,
    TENCENT_PROVIDER as STOCK_PROVIDER,
    build_default_chain_definitions,
)
from examples.shanghai_index_ma_backtest import (
    ADJUST as INDEX_ADJUST,
    FREQUENCY as INDEX_FREQUENCY,
    SYMBOL as BENCHMARK_SYMBOL,
    TENCENT_PROVIDER as INDEX_PROVIDER,
)
from runtime.paths import RuntimePaths


@dataclass(frozen=True)
class MainlineCacheSyncResult:
    """主线行情缓存同步摘要。"""

    requested_date: date
    stock_symbols: int
    fund_symbols: int
    index_symbols: int
    rows_written: int
    missing_symbols: tuple[str, ...]


def sync_mainline_cache_from_increment(
    paths: RuntimePaths,
    account_id: int,
    requested_date: date,
    cache_path: Path,
) -> MainlineCacheSyncResult:
    """把 DuckDB 增量行情同步到主线链动使用的 SQLite 行情缓存。

    策略逻辑仍然只通过原来的 MarketDataCache 读取数据；这里仅补齐当日
    增量，确保系统化调度不依赖人工 agent 去刷新腾讯接口。
    """
    chains = build_default_chain_definitions()
    fund_symbols = tuple(sorted({chain.proxy_symbol for chain in chains}))
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account = store.get_account(account_id)
        position_symbols = {str(item["symbol"]) for item in store.list_positions(account_id)}
    finally:
        store.close()

    chain_stock_symbols = {stock.symbol for chain in chains for stock in chain.stocks}
    stock_symbols = tuple(sorted(position_symbols | chain_stock_symbols))
    start_date = _parse_date(account["start_date"]) - timedelta(days=WARMUP_DAYS)

    cache = MarketDataCache(cache_path)
    missing: list[str] = []
    rows_written = 0
    try:
        rows_written += _sync_stock_bars(
            cache,
            paths.live_market_increment_path,
            stock_symbols,
            start_date,
            requested_date,
            missing,
        )
        rows_written += _sync_fund_bars(
            cache,
            paths.benchmark_increment_path,
            fund_symbols,
            start_date,
            requested_date,
            missing,
        )
        rows_written += _sync_index_bars(
            cache,
            paths.benchmark_increment_path,
            (BENCHMARK_SYMBOL,),
            start_date,
            requested_date,
            missing,
        )
    finally:
        cache.close()

    return MainlineCacheSyncResult(
        requested_date=requested_date,
        stock_symbols=len(stock_symbols),
        fund_symbols=len(fund_symbols),
        index_symbols=1,
        rows_written=rows_written,
        missing_symbols=tuple(sorted(set(missing))),
    )


def mainline_proxy_fund_symbols() -> tuple[str, ...]:
    """返回主线链动强弱判断依赖的 ETF 代理标的。"""
    return tuple(sorted({chain.proxy_symbol for chain in build_default_chain_definitions()}))


def _sync_stock_bars(
    cache: MarketDataCache,
    duckdb_path: Path,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    missing: list[str],
) -> int:
    if not duckdb_path.exists():
        missing.extend(symbols)
        return 0
    frame = _load_joined_market_frame(duckdb_path, "daily", "adj_factor", symbols, start_date, end_date)
    return _write_raw_and_qfq(cache, frame, symbols, STOCK_PROVIDER, STOCK_FREQUENCY, missing)


def _sync_fund_bars(
    cache: MarketDataCache,
    duckdb_path: Path,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    missing: list[str],
) -> int:
    if not duckdb_path.exists():
        missing.extend(symbols)
        return 0
    frame = _load_joined_market_frame(duckdb_path, "fund_daily", "fund_adj", symbols, start_date, end_date)
    return _write_raw_and_qfq(cache, frame, symbols, STOCK_PROVIDER, STOCK_FREQUENCY, missing)


def _sync_index_bars(
    cache: MarketDataCache,
    duckdb_path: Path,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    missing: list[str],
) -> int:
    if not duckdb_path.exists():
        missing.extend(symbols)
        return 0
    frame = _load_market_frame(duckdb_path, "index_daily", symbols, start_date, end_date)
    rows_written = 0
    for symbol, group in frame.groupby("ts_code"):
        bars = _to_cache_bars(group)
        if bars.empty:
            missing.append(str(symbol))
            continue
        rows_written += _upsert_with_coverage(cache, INDEX_PROVIDER, str(symbol), INDEX_FREQUENCY, INDEX_ADJUST, bars)
    missing.extend(symbol for symbol in symbols if symbol not in set(frame["ts_code"].astype(str)))
    return rows_written


def _write_raw_and_qfq(
    cache: MarketDataCache,
    frame: pd.DataFrame,
    symbols: Sequence[str],
    provider: str,
    frequency: str,
    missing: list[str],
) -> int:
    rows_written = 0
    present = set(frame["ts_code"].astype(str)) if not frame.empty else set()
    for symbol, group in frame.groupby("ts_code"):
        symbol_text = str(symbol)
        raw_bars = _to_cache_bars(group)
        qfq_bars = _to_qfq_cache_bars(cache, symbol_text, group, provider, frequency)
        rows_written += _upsert_with_coverage(cache, provider, symbol_text, frequency, "none", raw_bars)
        rows_written += _upsert_with_coverage(cache, provider, symbol_text, frequency, STOCK_ADJUST, qfq_bars)
    missing.extend(symbol for symbol in symbols if symbol not in present)
    return rows_written


def _load_market_frame(
    duckdb_path: Path,
    table: str,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    import duckdb

    if not symbols:
        return pd.DataFrame()
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        return con.execute(
            f"""
            SELECT ts_code, trade_date, open, high, low, close, vol, amount
            FROM {table}
            WHERE ts_code IN (SELECT * FROM UNNEST(?))
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY ts_code, trade_date
            """,
            [list(symbols), _fmt_yyyymmdd(start_date), _fmt_yyyymmdd(end_date)],
        ).fetchdf()


def _load_joined_market_frame(
    duckdb_path: Path,
    market_table: str,
    factor_table: str,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    import duckdb

    if not symbols:
        return pd.DataFrame()
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        return con.execute(
            f"""
            SELECT
              d.ts_code, d.trade_date, d.open, d.high, d.low, d.close,
              d.vol, d.amount, a.adj_factor
            FROM {market_table} d
            JOIN {factor_table} a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.ts_code IN (SELECT * FROM UNNEST(?))
              AND d.trade_date >= ?
              AND d.trade_date <= ?
            ORDER BY d.ts_code, d.trade_date
            """,
            [list(symbols), _fmt_yyyymmdd(start_date), _fmt_yyyymmdd(end_date)],
        ).fetchdf()


def _to_cache_bars(group: pd.DataFrame) -> pd.DataFrame:
    if group.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])
    result = group.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d")
    result = result.set_index("trade_date").sort_index()
    result["volume"] = result.get("vol", 0.0)
    return result[["open", "high", "low", "close", "volume", "amount"]]


def _to_qfq_cache_bars(
    cache: MarketDataCache,
    symbol: str,
    group: pd.DataFrame,
    provider: str,
    frequency: str,
) -> pd.DataFrame:
    raw = _to_cache_bars(group)
    if raw.empty:
        return raw
    factors = group.copy()
    factors["trade_date"] = pd.to_datetime(factors["trade_date"], format="%Y%m%d")
    factors = factors.set_index("trade_date").sort_index()["adj_factor"].astype(float)
    scale = _resolve_qfq_scale(cache, symbol, provider, frequency, group)
    adjusted = raw.copy()
    for column in ["open", "high", "low", "close"]:
        adjusted[column] = raw[column].astype(float) * factors / scale
    return adjusted


def _resolve_qfq_scale(
    cache: MarketDataCache,
    symbol: str,
    provider: str,
    frequency: str,
    group: pd.DataFrame,
) -> float:
    latest = _latest_cached_bar(cache, provider, symbol, frequency, STOCK_ADJUST)
    if latest is not None:
        latest_date, latest_close = latest
        match = group[group["trade_date"].astype(str).eq(_fmt_yyyymmdd(latest_date))]
        if not match.empty and latest_close > 0:
            row = match.iloc[-1]
            return float(row["close"]) * float(row["adj_factor"]) / latest_close
    first_factor = float(group.sort_values("trade_date")["adj_factor"].iloc[0])
    return first_factor if first_factor > 0 else 1.0


def _latest_cached_bar(
    cache: MarketDataCache,
    provider: str,
    symbol: str,
    frequency: str,
    adjust: str,
) -> tuple[date, float] | None:
    row = cache.conn.execute(
        """
        SELECT trade_time, close
        FROM market_ohlcv_bar
        WHERE provider = ? AND symbol = ? AND frequency = ? AND adjust = ?
        ORDER BY trade_time DESC
        LIMIT 1
        """,
        (provider, symbol, frequency, adjust),
    ).fetchone()
    if row is None:
        return None
    return _parse_date(row["trade_time"]), float(row["close"])


def _upsert_with_coverage(
    cache: MarketDataCache,
    provider: str,
    symbol: str,
    frequency: str,
    adjust: str,
    bars: pd.DataFrame,
) -> int:
    if bars.empty:
        return 0
    cache.upsert_bars(provider, symbol, frequency, adjust, bars)
    start = pd.Timestamp(bars.index.min()).date()
    end = pd.Timestamp(bars.index.max()).date()
    cache.record_coverage(provider, symbol, frequency, adjust, start, end)
    return len(bars)


def _parse_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _fmt_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")
