"""主线链动增量行情缓存同步测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.cache import MarketDataCache
from backtest.paper_trading import PaperTradingStore
from data.tushare_benchmark_incremental import BenchmarkIncrementalStore
from data.tushare_incremental import IncrementalDuckDBStore
from runtime.mainline_cache_sync import sync_mainline_cache_from_increment
from runtime.paths import RuntimePaths


def _market_row(symbol: str, trade_date: str, close: float) -> dict:
    """构造 Tushare 日线行，字段保持和增量库一致。"""
    return {
        "ts_code": symbol,
        "trade_date": trade_date,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "pre_close": close - 0.5,
        "change": 0.5,
        "pct_chg": 1.0,
        "vol": 1000.0,
        "amount": 2000.0,
    }


def _factor_row(symbol: str, trade_date: str, factor: float) -> dict:
    return {"ts_code": symbol, "trade_date": trade_date, "adj_factor": factor}


def _seed_account(path: Path) -> int:
    store = PaperTradingStore(path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1000000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-06-01",
        )
        order_id = store.record_pending_order(
            account_id,
            "2026-06-01",
            "601138.SH",
            "工业富联",
            "BUY",
            10.0,
            1000,
        )
        store.fill_order(order_id, "2026-06-02", 10.0)
        return account_id
    finally:
        store.close()


def test_sync_mainline_cache_from_tushare_increment_updates_today_bars(tmp_path: Path) -> None:
    """DuckDB 增量应同步到主线旧 SQLite 缓存，避免每日观察日期滞后。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    account_id = _seed_account(paths.paper_trading_path)

    daily_store = IncrementalDuckDBStore(paths.live_market_increment_path)
    daily_store.upsert(
        pd.DataFrame([
            _market_row("601138.SH", "20260629", 10.0),
            _market_row("601138.SH", "20260630", 11.0),
        ]),
        pd.DataFrame([
            _factor_row("601138.SH", "20260629", 2.0),
            _factor_row("601138.SH", "20260630", 2.2),
        ]),
    )
    benchmark_store = BenchmarkIncrementalStore(paths.benchmark_increment_path)
    benchmark_store.upsert_fund(pd.DataFrame([
        _market_row("159695.SZ", "20260629", 20.0),
        _market_row("159695.SZ", "20260630", 22.0),
    ]))
    benchmark_store.upsert_fund_adj(pd.DataFrame([
        _factor_row("159695.SZ", "20260629", 1.0),
        _factor_row("159695.SZ", "20260630", 1.1),
    ]))
    benchmark_store.upsert_index(pd.DataFrame([
        _market_row("000001.SH", "20260630", 3000.0),
    ]))

    cache_path = paths.data_dir / "market_cache.sqlite3"
    cache = MarketDataCache(cache_path)
    try:
        previous_stock = pd.DataFrame(
            {"open": [99.0], "high": [101.0], "low": [98.0], "close": [100.0], "volume": [1.0], "amount": [1.0]},
            index=pd.to_datetime(["2026-06-29"]),
        )
        previous_fund = pd.DataFrame(
            {"open": [39.0], "high": [41.0], "low": [38.0], "close": [40.0], "volume": [1.0], "amount": [1.0]},
            index=pd.to_datetime(["2026-06-29"]),
        )
        cache.upsert_bars("tushare", "601138.SH", "1d", "qfq", previous_stock)
        cache.upsert_bars("tushare", "159695.SZ", "1d", "qfq", previous_fund)
    finally:
        cache.close()

    result = sync_mainline_cache_from_increment(paths, account_id, date(2026, 6, 30), cache_path)

    cache = MarketDataCache(cache_path)
    try:
        stock_qfq = cache.read_bars("tushare", "601138.SH", "1d", "qfq", date(2026, 6, 30), date(2026, 6, 30))
        stock_raw = cache.read_bars("tushare", "601138.SH", "1d", "none", date(2026, 6, 30), date(2026, 6, 30))
        fund_qfq = cache.read_bars("tushare", "159695.SZ", "1d", "qfq", date(2026, 6, 30), date(2026, 6, 30))
        index_raw = cache.read_bars("tushare", "000001.SH", "1d", "none", date(2026, 6, 30), date(2026, 6, 30))
    finally:
        cache.close()

    assert result.rows_written >= 6
    assert round(float(stock_qfq["close"].iloc[0]), 2) == 121.0
    assert round(float(stock_raw["close"].iloc[0]), 2) == 11.0
    assert round(float(fund_qfq["close"].iloc[0]), 2) == 48.4
    assert round(float(index_raw["close"].iloc[0]), 2) == 3000.0
