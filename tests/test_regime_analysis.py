"""
Milestone 2.2 市场状态分析框架测试。
"""

from __future__ import annotations

import unittest

import pandas as pd

from backtest.regime_analysis import DefaultRegimeClassifier, RegimeMetrics, RegimeSplitter


class TestRegimeAnalysis(unittest.TestCase):
    """验证 regime 分析接口层不依赖外部市场状态数据。"""

    def test_default_regime_classifier_returns_all_time(self):
        """默认分类器当前只返回 ALL_TIME。"""
        classifier = DefaultRegimeClassifier()

        self.assertEqual(classifier.classify(pd.Timestamp("2024-01-02")), "ALL_TIME")

    def test_regime_splitter_groups_backtest_curve_by_regime(self):
        """RegimeSplitter 能把回测净值序列按 regime 分组。"""
        result = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
                "total_value": [1_000_000.0, 1_010_000.0, 1_005_000.0],
            }
        )
        splitter = RegimeSplitter(DefaultRegimeClassifier())

        grouped = splitter.split(result)

        self.assertEqual(set(grouped), {"ALL_TIME"})
        self.assertEqual(len(grouped["ALL_TIME"]), 3)
        self.assertIn("regime", grouped["ALL_TIME"].columns)
        self.assertTrue((grouped["ALL_TIME"]["regime"] == "ALL_TIME").all())

    def test_regime_metrics_outputs_expected_structure(self):
        """RegimeMetrics 输出年化收益、最大回撤和 Sharpe。"""
        curve = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
                "total_value": [100.0, 102.0, 101.0, 104.0],
            }
        )

        metrics = RegimeMetrics().calculate(curve)

        self.assertEqual(set(metrics), {"annual_return", "max_drawdown", "sharpe"})
        self.assertGreater(metrics["annual_return"], 0)
        self.assertLess(metrics["max_drawdown"], 0)
        self.assertGreater(metrics["sharpe"], 0)


if __name__ == "__main__":
    unittest.main()
