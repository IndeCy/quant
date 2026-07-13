"""主线链动 Tushare 历史回填测试。"""

from __future__ import annotations

import pandas as pd

from backtest.cache import MarketDataCache
from examples.compare_chain_stock_selection import build_default_chain_definitions
from runtime.mainline_tushare_backfill import backfill_mainline_tushare_cache
from runtime.paths import RuntimePaths


class FakeMainlineTushareClient:
    """按标的返回最小历史数据，验证 qfq 口径和缓存 key。"""

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _market(ts_code)

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _factor(ts_code)

    def fund_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _market(ts_code)

    def fund_adj(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _factor(ts_code)

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _market(ts_code)


def test_backfill_mainline_tushare_cache_writes_tushare_none_and_qfq(tmp_path) -> None:
    """回填应写入 provider=tushare，并用最新 adj_factor 计算前复权。"""
    paths = RuntimePaths(tmp_path / "runtime")
    result = backfill_mainline_tushare_cache(
        paths=paths,
        client=FakeMainlineTushareClient(),
        start_date="20240101",
        end_date="20240102",
        sleep_seconds=0.0,
    )

    first_stock = build_default_chain_definitions()[0].stocks[0].symbol
    cache = MarketDataCache(paths.data_dir / "market_cache.sqlite3")
    try:
        raw = cache.read_bars("tushare", first_stock, "1d", "none", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-02").date())
        qfq = cache.read_bars("tushare", first_stock, "1d", "qfq", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-02").date())
        index_raw = cache.read_bars("tushare", "000001.SH", "1d", "none", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-02").date())
    finally:
        cache.close()

    assert result.missing_symbols == ()
    assert result.rows_written > 0
    assert raw["close"].tolist() == [10.0, 20.0]
    assert qfq["close"].round(4).tolist() == [5.0, 20.0]
    assert index_raw["close"].tolist() == [10.0, 20.0]


def _market(symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(symbol, "20240101", 10.0),
            _row(symbol, "20240102", 20.0),
        ]
    )


def _factor(symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_code": symbol, "trade_date": "20240101", "adj_factor": 1.0},
            {"ts_code": symbol, "trade_date": "20240102", "adj_factor": 2.0},
        ]
    )


def _row(symbol: str, trade_date: str, close: float) -> dict[str, object]:
    return {
        "ts_code": symbol,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "pre_close": close,
        "change": 0.0,
        "pct_chg": 0.0,
        "vol": 100.0,
        "amount": 1000.0,
    }
