"""
Milestone 2.1 Core-Satellite 示例测试。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.milestone2_core_satellite_portfolio import run_milestone2_comparison


class TestMilestone2CoreSatelliteExample(unittest.TestCase):
    """验证示例能输出 Satellite alpha allocation 对比结论。"""

    def test_comparison_outputs_core_satellite_and_combined_rows(self):
        result = run_milestone2_comparison(write_report=False)

        self.assertEqual(
            set(result["组合"]),
            {"Core低波", "Satellite旧等权", "Satellite Alpha", "Core-Satellite Alpha"},
        )
        self.assertIn("总收益率", result.columns)
        self.assertIn("最大回撤", result.columns)
        self.assertIn("平均月换手", result.columns)
        self.assertIn("稳定性评分", result.columns)

    def test_combined_portfolio_is_more_stable_than_satellite(self):
        result = run_milestone2_comparison(write_report=False).set_index("组合")

        self.assertGreaterEqual(
            result.loc["Core-Satellite Alpha", "最大回撤"],
            result.loc["Satellite旧等权", "最大回撤"],
        )
        self.assertLessEqual(
            result.loc["Core-Satellite Alpha", "年化波动率"],
            result.loc["Satellite旧等权", "年化波动率"],
        )
        self.assertLessEqual(result.loc["Core-Satellite Alpha", "平均月换手"], 0.35)

    def test_satellite_alpha_improves_noise_source(self):
        result = run_milestone2_comparison(write_report=False).set_index("组合")

        self.assertLess(result.loc["Satellite旧等权", "总收益率"], 0)
        self.assertGreater(result.loc["Satellite Alpha", "总收益率"], 0)
        self.assertGreater(
            result.loc["Satellite Alpha", "总收益率"],
            result.loc["Satellite旧等权", "总收益率"],
        )
        self.assertLess(
            result.loc["Satellite Alpha", "平均月换手"],
            result.loc["Satellite旧等权", "平均月换手"],
        )


if __name__ == "__main__":
    unittest.main()
