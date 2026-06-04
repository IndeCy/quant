"""
测试 HTML 报表渲染
"""

import unittest
import sys
import os

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.report import build_backtest_report_html


class TestBacktestReport(unittest.TestCase):
    """测试回测报表页面生成"""

    def test_build_backtest_report_html_contains_metrics_and_trades(self):
        """报表页面应包含核心指标、交易明细和资金曲线数据"""
        daily_values = pd.DataFrame(
            {
                "total_value": [1_000_000.0, 1_020_000.0, 1_010_000.0],
                "cash": [500_000.0, 520_000.0, 1_010_000.0],
                "positions_value": [500_000.0, 500_000.0, 0.0],
                "returns": [0.0, 0.02, -0.0098],
                "cumulative_returns": [0.0, 0.02, 0.01],
            },
            index=pd.date_range("2026-05-27", periods=3, freq="D"),
        )
        trades = [
            {
                "date": pd.Timestamp("2026-05-27"),
                "symbol": "000001.SH",
                "quantity": 200,
                "price": 4100.0,
                "commission": 250.0,
            }
        ]
        summary = {
            "总收益率": 0.01,
            "基线总收益率": 0.005,
            "超额收益率": 0.005,
            "年化收益率": 0.12,
            "基线年化收益率": 0.06,
            "年化超额收益率": 0.06,
            "夏普比率": 1.2,
            "最大回撤": -0.02,
            "胜率": 0.5,
            "波动率": 0.08,
            "交易次数": 1,
            "最终资产": 1_010_000.0,
        }

        html = build_backtest_report_html(
            title="上证指数双均线回测报表",
            subtitle="MA5 / MA20",
            summary=summary,
            daily_values=daily_values,
            trades=trades,
        )

        self.assertIn("上证指数双均线回测报表", html)
        self.assertIn("总收益率", html)
        self.assertIn("基线总收益率", html)
        self.assertIn("超额收益率", html)
        self.assertIn("1.00%", html)
        self.assertIn("0.50%", html)
        self.assertIn("000001.SH", html)
        self.assertIn("<svg", html)


if __name__ == "__main__":
    unittest.main()
