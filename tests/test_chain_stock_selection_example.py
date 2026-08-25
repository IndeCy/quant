"""
测试产业链选股 ABC 对比入口
"""

import unittest

from examples.compare_chain_stock_selection import (
    build_demo_chain_inputs,
    format_chain_selection_result,
    parse_tencent_stock_payload,
    run_chain_selection_comparison,
)


class TestChainStockSelectionExample(unittest.TestCase):
    """验证 ABC 三类策略能统一输出对比表。"""

    def test_demo_comparison_returns_three_strategy_rows(self):
        """离线样例应返回 A/B/C 三种策略结果。"""
        chains, stock_bars, market_bars = build_demo_chain_inputs()

        result = run_chain_selection_comparison(chains, stock_bars, market_bars)

        self.assertEqual(result["方案"].tolist(), ["A", "B", "C"])
        self.assertIn("总收益率", result.columns)
        self.assertIn("基线收益率", result.columns)
        self.assertIn("超额收益率", result.columns)

    def test_format_result_prints_percent_columns(self):
        """格式化输出应把收益和回撤展示为百分比。"""
        chains, stock_bars, market_bars = build_demo_chain_inputs()
        result = run_chain_selection_comparison(chains, stock_bars, market_bars)

        formatted = format_chain_selection_result(result)

        self.assertIn("A", formatted)
        self.assertIn("%", formatted)
        self.assertIn("超额收益率", formatted)

    def test_parse_tencent_stock_payload_supports_qfqday_key(self):
        """腾讯个股前复权 K 线使用 qfqday 字段，应能正确解析。"""
        payload = {
            "data": {
                "sh600584": {
                    "qfqday": [["2026-06-04", "79.00", "80.08", "81.86", "77.80", "2270520"]]
                }
            }
        }

        df = parse_tencent_stock_payload(payload, "sh600584")

        self.assertEqual(float(df["close"].iloc[0]), 80.08)


if __name__ == "__main__":
    unittest.main()
