"""
测试上证指数双均线回测示例
"""

import unittest
from datetime import date
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.cache import MarketDataCache
from examples.shanghai_index_ma_backtest import (
    ADJUST,
    EASTMONEY_PROVIDER,
    FREQUENCY,
    TENCENT_PROVIDER,
    build_recent_month_window,
    fetch_eastmoney_index_klines,
    fetch_tencent_index_klines,
    parse_eastmoney_klines,
    parse_tencent_klines,
)


class TestShanghaiIndexMaBacktest(unittest.TestCase):
    """测试上证指数回测示例中的数据准备逻辑"""

    def test_build_recent_month_window_keeps_history_padding(self):
        """最近一个月窗口需要保留均线预热所需的历史数据"""
        fetch_start, run_start, run_end = build_recent_month_window(
            today=date(2026, 5, 31),
            run_days=31,
            warmup_days=90,
        )

        self.assertEqual(run_end, date(2026, 5, 31))
        self.assertEqual(run_start, date(2026, 4, 30))
        self.assertEqual(fetch_start, date(2026, 1, 30))

    def test_parse_eastmoney_klines_returns_backtest_dataframe(self):
        """东财指数K线应转换成回测引擎需要的标准列"""
        raw_klines = [
            "2026-05-28,3840.10,3851.20,3860.00,3830.00,123456,789000000",
            "2026-05-29,3852.00,3868.50,3875.00,3848.00,223456,889000000",
        ]

        df = parse_eastmoney_klines(raw_klines)

        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume", "amount"])
        self.assertEqual(len(df), 2)
        self.assertEqual(str(df.index[0].date()), "2026-05-28")
        self.assertAlmostEqual(df.iloc[1]["close"], 3868.50)

    def test_fetch_eastmoney_index_klines_reads_covered_cache(self):
        """目标区间已被缓存覆盖时，不应再次请求东方财富接口"""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "market_cache.sqlite3"
            cache = MarketDataCache(cache_path)
            cached_df = pd.DataFrame(
                {
                    "open": [4100.0, 4110.0, 4120.0],
                    "high": [4110.0, 4120.0, 4130.0],
                    "low": [4090.0, 4100.0, 4110.0],
                    "close": [4105.0, 4115.0, 4125.0],
                    "volume": [1000.0, 1100.0, 1200.0],
                    "amount": [2000.0, 2100.0, 2200.0],
                },
                index=pd.date_range("2026-05-01", periods=3, freq="D"),
            )
            cache.upsert_bars(EASTMONEY_PROVIDER, "000001.SH", FREQUENCY, ADJUST, cached_df)
            cache.record_coverage(
                EASTMONEY_PROVIDER,
                "000001.SH",
                FREQUENCY,
                ADJUST,
                date(2026, 5, 1),
                date(2026, 5, 3),
            )
            cache.close()

            with patch(
                "examples.shanghai_index_ma_backtest._fetch_eastmoney_index_klines_remote",
                side_effect=AssertionError("缓存覆盖时不应该请求接口"),
            ):
                actual = fetch_eastmoney_index_klines(
                    "000001.SH",
                    date(2026, 5, 2),
                    date(2026, 5, 3),
                    cache_path=cache_path,
                )

        self.assertEqual(len(actual), 2)
        self.assertAlmostEqual(actual.iloc[-1]["close"], 4125.0)

    def test_parse_tencent_klines_returns_backtest_dataframe(self):
        """腾讯指数K线应转换成回测引擎需要的标准列"""
        raw_klines = [
            ["2026-05-28", "8640.20", "8655.30", "8700.00", "8600.00", "300000"],
            ["2026-05-29", "8650.10", "8408.74", "8660.00", "8390.00", "350000"],
        ]

        df = parse_tencent_klines(raw_klines)

        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume", "amount"])
        self.assertEqual(len(df), 2)
        self.assertEqual(str(df.index[0].date()), "2026-05-28")
        self.assertAlmostEqual(df.iloc[1]["close"], 8408.74)
        self.assertAlmostEqual(df.iloc[1]["amount"], 0.0)

    def test_fetch_tencent_index_klines_reads_covered_cache(self):
        """腾讯目标区间已被缓存覆盖时，不应再次请求腾讯接口"""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "market_cache.sqlite3"
            cache = MarketDataCache(cache_path)
            cached_df = pd.DataFrame(
                {
                    "open": [8000.0, 8100.0, 8200.0],
                    "high": [8050.0, 8150.0, 8250.0],
                    "low": [7950.0, 8050.0, 8150.0],
                    "close": [8020.0, 8120.0, 8220.0],
                    "volume": [3000.0, 3100.0, 3200.0],
                    "amount": [0.0, 0.0, 0.0],
                },
                index=pd.date_range("2026-05-01", periods=3, freq="D"),
            )
            cache.upsert_bars(TENCENT_PROVIDER, "000852.SH", FREQUENCY, ADJUST, cached_df)
            cache.record_coverage(
                TENCENT_PROVIDER,
                "000852.SH",
                FREQUENCY,
                ADJUST,
                date(2026, 5, 1),
                date(2026, 5, 3),
            )
            cache.close()

            with patch(
                "examples.shanghai_index_ma_backtest._fetch_tencent_index_klines_remote",
                side_effect=AssertionError("缓存覆盖时不应该请求腾讯接口"),
            ):
                actual = fetch_tencent_index_klines(
                    "000852.SH",
                    date(2026, 5, 2),
                    date(2026, 5, 3),
                    cache_path=cache_path,
                )

        self.assertEqual(len(actual), 2)
        self.assertAlmostEqual(actual.iloc[-1]["close"], 8220.0)


if __name__ == "__main__":
    unittest.main()
