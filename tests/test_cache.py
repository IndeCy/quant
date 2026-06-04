"""
测试本地行情缓存
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from backtest.cache import MarketDataCache, load_or_fetch_ohlcv


class TestMarketDataCache(unittest.TestCase):
    """测试 OHLCV 时序缓存"""

    def setUp(self):
        """每个用例使用独立 SQLite 文件，避免缓存数据互相污染"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "market_cache.sqlite3"
        self.cache = MarketDataCache(self.cache_path)

    def tearDown(self):
        """清理测试缓存文件"""
        self.cache.close()
        self.temp_dir.cleanup()

    def _sample_df(self, start: str, periods: int) -> pd.DataFrame:
        """构造测试用日K数据"""
        index = pd.date_range(start, periods=periods, freq="D")
        return pd.DataFrame(
            {
                "open": [10.0 + i for i in range(periods)],
                "high": [11.0 + i for i in range(periods)],
                "low": [9.0 + i for i in range(periods)],
                "close": [10.5 + i for i in range(periods)],
                "volume": [1000.0 + i for i in range(periods)],
                "amount": [2000.0 + i for i in range(periods)],
            },
            index=index,
        )

    def test_upsert_and_read_ohlcv_bars(self):
        """按日写入后，应能按日期范围读取标准回测DataFrame"""
        df = self._sample_df("2026-05-01", 3)

        self.cache.upsert_bars("eastmoney", "000001.SH", "1d", "none", df)
        actual = self.cache.read_bars(
            "eastmoney",
            "000001.SH",
            "1d",
            "none",
            date(2026, 5, 2),
            date(2026, 5, 3),
        )

        self.assertEqual(list(actual.columns), ["open", "high", "low", "close", "volume", "amount"])
        self.assertEqual(len(actual), 2)
        self.assertAlmostEqual(actual.iloc[0]["close"], 11.5)

    def test_load_or_fetch_uses_cache_when_interval_is_covered(self):
        """目标区间被覆盖时，应直接读缓存，不再调用外部接口"""
        df = self._sample_df("2026-05-01", 10)
        self.cache.upsert_bars("eastmoney", "000001.SH", "1d", "none", df)
        self.cache.record_coverage(
            "eastmoney",
            "000001.SH",
            "1d",
            "none",
            date(2026, 5, 1),
            date(2026, 5, 10),
        )

        def fetcher(_start: date, _end: date) -> pd.DataFrame:
            raise AssertionError("缓存已覆盖时不应该请求接口")

        actual = load_or_fetch_ohlcv(
            cache=self.cache,
            provider="eastmoney",
            symbol="000001.SH",
            frequency="1d",
            adjust="none",
            start_date=date(2026, 5, 3),
            end_date=date(2026, 5, 5),
            fetcher=fetcher,
        )

        self.assertEqual(len(actual), 3)
        self.assertEqual(str(actual.index[0].date()), "2026-05-03")

    def test_any_provider_uses_cache_when_interval_is_covered(self):
        """任意数据源只要缓存覆盖，都必须直接读缓存"""
        df = self._sample_df("2026-05-01", 3)
        self.cache.upsert_bars("custom_provider", "TEST.SH", "1d", "none", df)
        self.cache.record_coverage(
            "custom_provider",
            "TEST.SH",
            "1d",
            "none",
            date(2026, 5, 1),
            date(2026, 5, 3),
        )

        def fetcher(_start: date, _end: date) -> pd.DataFrame:
            raise AssertionError("任意provider缓存已覆盖时都不应该请求接口")

        actual = load_or_fetch_ohlcv(
            cache=self.cache,
            provider="custom_provider",
            symbol="TEST.SH",
            frequency="1d",
            adjust="none",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            fetcher=fetcher,
        )

        self.assertEqual(len(actual), 3)
        self.assertAlmostEqual(actual.iloc[-1]["close"], 12.5)

    def test_load_or_fetch_fetches_only_missing_tail(self):
        """目标区间只有尾部缺失时，只补拉缺失尾段"""
        df = self._sample_df("2026-05-01", 5)
        self.cache.upsert_bars("eastmoney", "000001.SH", "1d", "none", df)
        self.cache.record_coverage(
            "eastmoney",
            "000001.SH",
            "1d",
            "none",
            date(2026, 5, 1),
            date(2026, 5, 5),
        )
        fetched_ranges = []

        def fetcher(start: date, end: date) -> pd.DataFrame:
            fetched_ranges.append((start, end))
            return self._sample_df("2026-05-06", 2)

        actual = load_or_fetch_ohlcv(
            cache=self.cache,
            provider="eastmoney",
            symbol="000001.SH",
            frequency="1d",
            adjust="none",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 7),
            fetcher=fetcher,
        )

        self.assertEqual(fetched_ranges, [(date(2026, 5, 6), date(2026, 5, 7))])
        self.assertEqual(len(actual), 7)

    def test_disjoint_coverage_does_not_hide_middle_gap(self):
        """离散覆盖区间不能被误判成完整覆盖，缺口仍需补拉"""
        first = self._sample_df("2026-05-01", 2)
        last = self._sample_df("2026-05-05", 2)
        self.cache.upsert_bars("eastmoney", "000001.SH", "1d", "none", first)
        self.cache.upsert_bars("eastmoney", "000001.SH", "1d", "none", last)
        self.cache.record_coverage("eastmoney", "000001.SH", "1d", "none", date(2026, 5, 1), date(2026, 5, 2))
        self.cache.record_coverage("eastmoney", "000001.SH", "1d", "none", date(2026, 5, 5), date(2026, 5, 6))
        fetched_ranges = []

        def fetcher(start: date, end: date) -> pd.DataFrame:
            fetched_ranges.append((start, end))
            return self._sample_df("2026-05-03", 2)

        actual = load_or_fetch_ohlcv(
            cache=self.cache,
            provider="eastmoney",
            symbol="000001.SH",
            frequency="1d",
            adjust="none",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 6),
            fetcher=fetcher,
        )

        self.assertEqual(fetched_ranges, [(date(2026, 5, 3), date(2026, 5, 4))])
        self.assertEqual(len(actual), 6)

    def test_load_or_fetch_splits_large_missing_interval(self):
        """大缺口应拆成小段请求，避免行情接口因区间过长断开"""
        fetched_ranges = []

        def fetcher(start: date, end: date) -> pd.DataFrame:
            fetched_ranges.append((start, end))
            days = (end - start).days + 1
            return self._sample_df(start.isoformat(), days)

        actual = load_or_fetch_ohlcv(
            cache=self.cache,
            provider="eastmoney",
            symbol="000852.SH",
            frequency="1d",
            adjust="none",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 10),
            fetcher=fetcher,
            max_fetch_days=4,
        )

        self.assertEqual(
            fetched_ranges,
            [
                (date(2026, 1, 1), date(2026, 1, 4)),
                (date(2026, 1, 5), date(2026, 1, 8)),
                (date(2026, 1, 9), date(2026, 1, 10)),
            ],
        )
        self.assertEqual(len(actual), 10)


if __name__ == "__main__":
    unittest.main()
