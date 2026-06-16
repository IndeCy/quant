"""
M0 可信回测硬边界审计测试
"""

import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.benchmark import build_benchmark_curve
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.strategies import BuyAndHoldStrategy
from data.financial import FinancialDataPortal, FinancialStatementStore


class TestM0Audit(unittest.TestCase):
    """把 M0 阻断点固化成测试。"""

    def _bars(self, dates=None) -> pd.DataFrame:
        dates = dates or pd.to_datetime(["2024-01-02", "2024-01-03"])
        return pd.DataFrame(
            {
                "date": dates,
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.8, 10.8],
                "close": [10.2, 11.2],
                "volume": [1000, 1000],
            }
        )

    def test_benchmark_price_input_is_cleaned_by_schema(self):
        """基准价格读取也必须经过统一 schema，支持 date 列而非裸索引。"""
        benchmark_bars = self._bars()
        target_index = pd.to_datetime(["2024-01-02", "2024-01-03"])

        curve = build_benchmark_curve(benchmark_bars, target_index, 100000.0)

        self.assertEqual(list(curve.index), list(target_index))
        self.assertAlmostEqual(curve.iloc[0], 100000.0)
        self.assertGreater(curve.iloc[-1], curve.iloc[0])

    def test_engine_rejects_mixed_adjustment_policy(self):
        """同一次回测不同标的复权口径混用时必须失败，不能静默回测。"""
        manager = DataManager()
        manager.load_data("AAA.SZ", self._bars(), adjust="qfq")
        manager.load_data("BBB.SZ", self._bars(), adjust="none")

        engine = BacktestEngine(manager, BuyAndHoldStrategy("AAA.SZ"))

        with self.assertRaises(ValueError):
            engine.run()

    def test_financial_portal_hides_raw_records_from_factor_layer(self):
        """因子层只能拿 as-of 门面，不能直接访问原始财报 records。"""
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
                }
            ]
        )
        portal = FinancialDataPortal(store)

        self.assertFalse(hasattr(portal, "records"))
        self.assertEqual(portal.get_financial_snapshot("AAA.SZ", "2024-04-29"), {})


if __name__ == "__main__":
    unittest.main()
