"""
Phase 1.5 数据可信增强测试
"""

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.cache import MarketDataCache
from backtest.data import DataManager
from data.adjustment import AdjustType, normalize_adjust
from data.calendar import TradingCalendar
from data.financial import FinancialStatementStore


class TestPhase15DataContracts(unittest.TestCase):
    """验证真实交易日历、复权口径和财报 as-of 接口。"""

    def test_ashare_calendar_uses_real_holidays_not_business_days(self):
        """春节假期和调休工作日不能被误判为交易日。"""
        calendar = TradingCalendar()

        self.assertFalse(calendar.is_trading_day("2024-02-09"))
        self.assertFalse(calendar.is_trading_day("2024-02-18"))
        self.assertTrue(calendar.is_trading_day("2024-02-19"))
        self.assertEqual(calendar.next_trading_day("2024-02-08"), pd.Timestamp("2024-02-19"))

    def test_ashare_calendar_lists_only_real_trading_days_in_range(self):
        """区间交易日列表应跳过春节长假。"""
        calendar = TradingCalendar()

        actual = calendar.trading_days("2024-02-07", "2024-02-20")

        self.assertEqual(
            actual,
            [
                pd.Timestamp("2024-02-07"),
                pd.Timestamp("2024-02-08"),
                pd.Timestamp("2024-02-19"),
                pd.Timestamp("2024-02-20"),
            ],
        )

    def test_adjust_type_is_normalized_and_validated(self):
        """复权口径只允许 none/qfq/hfq，并支持常见别名归一化。"""
        self.assertEqual(normalize_adjust("none"), AdjustType.NONE)
        self.assertEqual(normalize_adjust("前复权"), AdjustType.QFQ)
        self.assertEqual(normalize_adjust("hfq"), AdjustType.HFQ)
        with self.assertRaises(ValueError):
            normalize_adjust("bad-adjust")

    def test_data_manager_records_adjustment_policy(self):
        """DataManager 应记录每只标的加载数据的复权口径。"""
        manager = DataManager()
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02"]),
                "open": [10.0],
                "high": [10.2],
                "low": [9.8],
                "close": [10.1],
                "volume": [1000],
            }
        )

        manager.load_data("AAA.SZ", bars, adjust="qfq")

        self.assertEqual(manager.get_adjust("AAA.SZ"), AdjustType.QFQ)
        self.assertEqual(manager.get_data("AAA.SZ").attrs["adjust"], "qfq")

    def test_market_cache_rejects_unknown_adjustment(self):
        """行情缓存 key 中的复权口径必须显式合法。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = MarketDataCache(Path(temp_dir) / "cache.sqlite3")
            try:
                with self.assertRaises(ValueError):
                    cache.read_bars("mock", "AAA.SZ", "1d", "bad-adjust", date(2024, 1, 1), date(2024, 1, 2))
            finally:
                cache.close()

    def test_financial_as_of_hides_reports_published_after_trade_date(self):
        """报告期已结束但尚未披露的数据，对回测日期不可见。"""
        store = FinancialStatementStore.from_records(
            [
                {
                    "symbol": "AAA.SZ",
                    "report_period": "2023-12-31",
                    "publish_date": "2024-04-30",
                    "statement_type": "income",
                    "field_name": "roe",
                    "field_value": 0.12,
                    "source": "mock",
                },
                {
                    "symbol": "AAA.SZ",
                    "report_period": "2023-09-30",
                    "publish_date": "2023-10-28",
                    "statement_type": "income",
                    "field_name": "roe",
                    "field_value": 0.09,
                    "source": "mock",
                },
            ]
        )

        before_publish = store.get_financial_snapshot("AAA.SZ", "2024-04-29")
        after_publish = store.get_financial_snapshot("AAA.SZ", "2024-04-30")

        self.assertEqual(before_publish["roe"], 0.09)
        self.assertEqual(after_publish["roe"], 0.12)


if __name__ == "__main__":
    unittest.main()
