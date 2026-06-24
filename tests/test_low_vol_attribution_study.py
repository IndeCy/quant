"""
低波动策略收益来源归因研究测试。
"""

from __future__ import annotations

import unittest

import pandas as pd

from examples.low_vol_attribution_study import classify_attribution, quality_spread


class TestLowVolAttributionStudy(unittest.TestCase):
    """验证低波动归因判断逻辑。"""

    def test_quality_spread_treats_debt_ratio_as_lower_is_better(self):
        low_vol = pd.Series({"roe": 12.0, "roa": 6.0, "grossprofit_margin": 35.0, "tr_yoy": 10.0, "debt_to_assets": 40.0})
        market = pd.Series({"roe": 8.0, "roa": 4.0, "grossprofit_margin": 25.0, "tr_yoy": 5.0, "debt_to_assets": 55.0})

        spread = quality_spread(low_vol, market)

        self.assertGreater(spread["roe"], 0)
        self.assertGreater(spread["debt_to_assets_quality"], 0)

    def test_classify_attribution_detects_joint_effect(self):
        result = classify_attribution(
            excess_return=0.03,
            low_vol_realized_vol=0.12,
            market_realized_vol=0.20,
            quality_score=0.8,
        )

        self.assertEqual(result, "C. 低波动风险溢价与高质量公司暴露共同作用")


if __name__ == "__main__":
    unittest.main()
