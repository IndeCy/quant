"""
Milestone 2 因子资产组合化测试。
"""

import math
import unittest

from backtest.factor_portfolio import CoreSatelliteFactorPortfolio


class TestCoreSatelliteFactorPortfolio(unittest.TestCase):
    """验证 Core-Satellite 组合层独立于策略层。"""

    def test_allocation_control_enforces_70_30_between_sleeves(self):
        """Core/Satellite 信号只表达方向，权重由组合层控制为 70/30。"""
        constructor = CoreSatelliteFactorPortfolio(core_allocation=0.70, satellite_allocation=0.30)

        result = constructor.build(
            core_signals={"LOW_A": 99.0, "LOW_B": 1.0},
            satellite_signals={"MOM_A": 1000.0},
            risk_estimates={"LOW_A": 0.10, "LOW_B": 0.10, "MOM_A": 0.30},
        )

        self.assertAlmostEqual(sum(result.core_weights.values()), 0.70)
        self.assertAlmostEqual(sum(result.satellite_weights.values()), 0.30)
        self.assertAlmostEqual(sum(result.target_weights.values()), 1.0)
        self.assertNotAlmostEqual(result.target_weights["LOW_A"], 0.99)

    def test_risk_budgeting_prefers_lower_volatility_inside_sleeve(self):
        """同一 sleeve 内使用简单风险预算，低波动标的获得更高权重。"""
        constructor = CoreSatelliteFactorPortfolio(core_allocation=0.70, satellite_allocation=0.30)

        result = constructor.build(
            core_signals={"LOW_A": 1.0, "LOW_B": 1.0},
            satellite_signals={"MOM_A": 1.0, "MOM_B": 1.0},
            risk_estimates={"LOW_A": 0.08, "LOW_B": 0.20, "MOM_A": 0.15, "MOM_B": 0.30},
        )

        self.assertGreater(result.core_weights["LOW_A"], result.core_weights["LOW_B"])
        self.assertGreater(result.satellite_weights["MOM_A"], result.satellite_weights["MOM_B"])

    def test_turnover_constraint_scales_portfolio_level_change(self):
        """组合级换手超过阈值时，应从旧权重向目标权重部分移动。"""
        constructor = CoreSatelliteFactorPortfolio(
            core_allocation=0.70,
            satellite_allocation=0.30,
            max_turnover=0.20,
        )

        result = constructor.build(
            core_signals={"LOW_NEW": 1.0},
            satellite_signals={"MOM_NEW": 1.0},
            risk_estimates={"LOW_NEW": 0.10, "MOM_NEW": 0.20},
            previous_weights={"LOW_OLD": 0.70, "MOM_OLD": 0.30},
        )

        self.assertLessEqual(result.turnover, 0.20)
        self.assertTrue(result.turnover_constraint_applied)
        self.assertGreater(result.target_weights["LOW_OLD"], 0.0)
        self.assertGreater(result.target_weights["LOW_NEW"], 0.0)

    def test_empty_satellite_reallocates_to_core_without_breaking_sum(self):
        """卫星没有信号时，资金留在 Core，不强行制造高换手增强仓。"""
        constructor = CoreSatelliteFactorPortfolio(core_allocation=0.70, satellite_allocation=0.30)

        result = constructor.build(
            core_signals={"LOW_A": 1.0, "LOW_B": 1.0},
            satellite_signals={},
            risk_estimates={"LOW_A": 0.10, "LOW_B": 0.20},
        )

        self.assertAlmostEqual(sum(result.core_weights.values()), 1.0)
        self.assertEqual(result.satellite_weights, {})
        self.assertAlmostEqual(sum(result.target_weights.values()), 1.0)

    def test_nan_risk_estimate_falls_back_to_default(self):
        """上游波动率缺失时，组合层不能产生 NaN 权重。"""
        constructor = CoreSatelliteFactorPortfolio()

        result = constructor.build(
            core_signals={"LOW_A": 1.0},
            satellite_signals={"MOM_A": 1.0},
            risk_estimates={"LOW_A": math.nan, "MOM_A": math.nan},
        )

        self.assertAlmostEqual(sum(result.target_weights.values()), 1.0)
        self.assertTrue(all(math.isfinite(weight) for weight in result.target_weights.values()))

    def test_satellite_confidence_signal_strength_changes_weight(self):
        """Satellite 使用信号强度连续映射，不再把正信号等同处理。"""
        constructor = CoreSatelliteFactorPortfolio(core_allocation=0.70, satellite_allocation=0.30)

        result = constructor.build(
            core_signals={"LOW_A": 1.0},
            satellite_signals={"MOM_STRONG": 3.0, "MOM_WEAK": 0.5},
            risk_estimates={"LOW_A": 0.08, "MOM_STRONG": 0.20, "MOM_WEAK": 0.20},
        )

        self.assertGreater(result.satellite_weights["MOM_STRONG"], result.satellite_weights["MOM_WEAK"])
        self.assertAlmostEqual(sum(result.satellite_weights.values()), 0.30)

    def test_satellite_volatility_scaling_can_offset_signal_strength(self):
        """Satellite 高波动资产即使信号更强，也会被波动率缩放降权。"""
        constructor = CoreSatelliteFactorPortfolio(core_allocation=0.70, satellite_allocation=0.30)

        result = constructor.build(
            core_signals={"LOW_A": 1.0},
            satellite_signals={"HIGH_VOL": 3.0, "LOW_VOL": 1.0},
            risk_estimates={"LOW_A": 0.08, "HIGH_VOL": 0.80, "LOW_VOL": 0.10},
        )

        self.assertGreater(result.satellite_weights["LOW_VOL"], result.satellite_weights["HIGH_VOL"])

    def test_satellite_turnover_penalty_downweights_fast_changing_signal(self):
        """Satellite 信号相对上期变化越大，权重应被 penalty 降低。"""
        constructor = CoreSatelliteFactorPortfolio(
            core_allocation=0.70,
            satellite_allocation=0.30,
            satellite_turnover_penalty=2.0,
        )

        result = constructor.build(
            core_signals={"LOW_A": 1.0},
            satellite_signals={"STABLE": 1.1, "JUMPY": 3.0},
            risk_estimates={"LOW_A": 0.08, "STABLE": 0.20, "JUMPY": 0.20},
            previous_satellite_signals={"STABLE": 1.0, "JUMPY": 0.1},
        )

        self.assertGreater(result.satellite_weights["STABLE"], result.satellite_weights["JUMPY"])


if __name__ == "__main__":
    unittest.main()
