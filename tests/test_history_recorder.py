"""
测试策略历史记录写入工具
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtest.history import StrategyHistoryStore
from backtest.history_recorder import record_comparison_results


class TestHistoryRecorder(unittest.TestCase):
    """测试批量回测结果落历史库"""

    def test_record_comparison_results_writes_each_strategy(self):
        """批量对比结果应逐条写入策略历史库"""
        comparison = pd.DataFrame(
            [
                {"策略": "MA_Cross", "策略类型": "趋势跟随", "总收益率": 0.1, "最大回撤": -0.05, "超额收益率": 0.02},
                {"策略": "RSI_Reversion", "策略类型": "均值回归", "总收益率": 0.03, "最大回撤": -0.02, "超额收益率": -0.05},
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StrategyHistoryStore(Path(temp_dir) / "strategy_history.sqlite3")
            try:
                run_ids = record_comparison_results(
                    store=store,
                    comparison=comparison,
                    symbol="000001.SH",
                    symbol_name="上证指数",
                    start_date="2025-06-04",
                    end_date="2026-06-04",
                    provider="tencent",
                    benchmark_symbol="000001.SH",
                    benchmark_name="上证指数",
                    strategy_params={"source": "classic_comparison"},
                )
                rows = store.query_runs(symbol="000001.SH")
            finally:
                store.close()

        self.assertEqual(len(run_ids), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["metrics"]["总收益率"], 0.03)
        self.assertEqual(rows[1]["strategy_params"]["source"], "classic_comparison")


if __name__ == "__main__":
    unittest.main()
