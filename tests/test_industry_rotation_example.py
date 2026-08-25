"""
测试行业轮动示例工具
"""

import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from examples.compare_industry_rotation import (
    build_real_proxy_rotation_inputs,
    format_rotation_result,
    run_industry_rotation_comparison,
)


class TestIndustryRotationExample(unittest.TestCase):
    """测试行业轮动对比入口"""

    def test_run_industry_rotation_comparison_outputs_metrics(self):
        """行业轮动示例应输出策略和基线对比指标"""
        dates = pd.date_range(start="2023-01-01", periods=60, freq="D")
        industry_bars = {
            "电力": pd.DataFrame({"close": range(100, 160), "open": range(100, 160), "high": range(101, 161), "low": range(99, 159), "volume": [1] * 60}, index=dates),
            "半导体": pd.DataFrame({"close": range(100, 220, 2), "open": range(100, 220, 2), "high": range(101, 221, 2), "low": range(99, 219, 2), "volume": [1] * 60}, index=dates),
            "银行": pd.DataFrame({"close": [100] * 60, "open": [100] * 60, "high": [101] * 60, "low": [99] * 60, "volume": [1] * 60}, index=dates),
        }
        market_bars = pd.DataFrame(
            {"close": range(100, 160), "open": range(100, 160), "high": range(101, 161), "low": range(99, 159), "volume": [1] * 60},
            index=dates,
        )

        result = run_industry_rotation_comparison(industry_bars, market_bars)

        self.assertIn("策略", result.columns)
        self.assertIn("总收益率", result.columns)
        self.assertIn("基线收益率", result.columns)
        self.assertEqual(result.iloc[0]["策略"], "Industry_Momentum_Rotation")

    def test_format_rotation_result_outputs_percent_text(self):
        """行业轮动结果格式化时应展示百分比文本"""
        result = pd.DataFrame(
            [{"策略": "Industry_Momentum_Rotation", "总收益率": 0.1, "年化收益率": 0.2, "最大回撤": -0.03, "夏普比率": 1.23, "交易次数": 2, "基线收益率": 0.05, "超额收益率": 0.05}]
        )

        text = format_rotation_result(result)

        self.assertIn("10.00%", text)
        self.assertIn("-3.00%", text)

    def test_build_real_proxy_rotation_inputs_uses_proxy_data_source(self):
        """真实行业代理输入应使用行业 ETF 数据源"""
        dates = pd.date_range(start="2023-01-01", periods=30, freq="D")
        bars = {
            "半导体": pd.DataFrame({"close": range(100, 130)}, index=dates),
            "电力": pd.DataFrame({"close": range(90, 120)}, index=dates),
        }
        market = pd.DataFrame({"close": range(80, 110)}, index=dates)

        with patch("examples.compare_industry_rotation.fetch_default_industry_proxy_bars", return_value=bars) as mock_fetch:
            industry_bars, market_bars = build_real_proxy_rotation_inputs(
                fetch_start=date(2023, 1, 1),
                fetch_end=date(2023, 1, 30),
                market_bars=market,
            )

        self.assertEqual(set(industry_bars.keys()), {"半导体", "电力"})
        self.assertEqual(len(market_bars), 30)
        mock_fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
