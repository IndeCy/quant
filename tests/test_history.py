"""
测试策略历史模块
"""

import tempfile
import unittest
from pathlib import Path

from backtest.history import StrategyHistoryStore


class TestStrategyHistoryStore(unittest.TestCase):
    """测试已验证策略历史记录"""

    def setUp(self):
        """每个用例使用独立 SQLite 文件"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "strategy_history.sqlite3"
        self.store = StrategyHistoryStore(self.db_path)

    def tearDown(self):
        """关闭连接并清理临时文件"""
        self.store.close()
        self.temp_dir.cleanup()

    def test_record_and_query_by_symbol_strategy(self):
        """历史记录应支持按标的和策略查询"""
        self.store.record_run(
            symbol="000852.SH",
            symbol_name="中证1000",
            strategy_name="MA_Cross",
            strategy_params={"short_window": 5, "long_window": 20},
            start_date="2024-06-02",
            end_date="2026-06-02",
            provider="tencent",
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            metrics={"总收益率": 0.5915, "超额收益率": 0.2739, "最大回撤": -0.1214},
            yearly_returns=[
                {"year": 2024, "strategy_return": 0.2967, "benchmark_return": 0.0888, "excess_return": 0.208},
                {"year": 2025, "strategy_return": 0.1892, "benchmark_return": 0.1841, "excess_return": 0.0051},
            ],
        )
        self.store.record_run(
            symbol="000001.SH",
            symbol_name="上证指数",
            strategy_name="MA_Cross",
            strategy_params={"short_window": 5, "long_window": 20},
            start_date="2024-06-02",
            end_date="2026-06-02",
            provider="tencent",
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            metrics={"总收益率": 0.3043, "超额收益率": -0.0133, "最大回撤": -0.0829},
            yearly_returns=[],
        )

        rows = self.store.query_runs(symbol="000852.SH", strategy_name="MA_Cross")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol_name"], "中证1000")
        self.assertAlmostEqual(rows[0]["metrics"]["总收益率"], 0.5915)
        self.assertEqual(rows[0]["strategy_params"]["short_window"], 5)

    def test_query_by_year_and_classify(self):
        """历史记录应支持按年度和维度分类"""
        self.store.record_run(
            symbol="000852.SH",
            symbol_name="中证1000",
            strategy_name="MA_Cross",
            strategy_params={"short_window": 5, "long_window": 20},
            start_date="2021-06-03",
            end_date="2026-06-02",
            provider="tencent",
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            metrics={"总收益率": 0.2236},
            yearly_returns=[
                {"year": 2024, "strategy_return": 0.1604, "benchmark_return": 0.0888, "excess_return": 0.0716},
                {"year": 2025, "strategy_return": 0.1060, "benchmark_return": 0.1841, "excess_return": -0.0781},
            ],
        )

        year_rows = self.store.query_yearly_returns(symbol="000852.SH", year=2024)
        classified = self.store.classify_runs()

        self.assertEqual(len(year_rows), 1)
        self.assertEqual(year_rows[0]["year"], 2024)
        self.assertAlmostEqual(year_rows[0]["strategy_return"], 0.1604)
        self.assertIn("000852.SH", classified["by_symbol"])
        self.assertIn("MA_Cross", classified["by_strategy"])
        self.assertIn(2024, classified["by_year"])


if __name__ == "__main__":
    unittest.main()
