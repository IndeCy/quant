"""
测试绩效分析模块
"""

import unittest
import sys
import os

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer


class TestPerformanceAnalyzer(unittest.TestCase):
    """测试绩效指标计算"""

    def test_flat_equity_curve_has_zero_sharpe_ratio(self):
        """资产曲线无波动时，夏普比率应返回0，避免浮点误差放大"""
        daily_values = pd.DataFrame(
            {
                "total_value": [1_000_000.0] * 20,
                "cash": [1_000_000.0] * 20,
                "positions_value": [0.0] * 20,
            },
            index=pd.date_range("2026-05-01", periods=20, freq="B"),
        )

        analyzer = PerformanceAnalyzer(daily_values, [], 1_000_000.0)

        self.assertEqual(analyzer.get_sharpe_ratio(), 0.0)


if __name__ == "__main__":
    unittest.main()
