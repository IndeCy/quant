"""
Milestone 5 资本规模与实盘可行性分析测试。
"""

from __future__ import annotations

import unittest

import pandas as pd

from backtest.capital_scaling import (
    CapitalScalingSimulator,
    ExecutionCostCurve,
    LiquidityStressTester,
    PortfolioFragilityTester,
    ScalingStabilityAnalyzer,
)


def sample_returns() -> pd.Series:
    """构造稳定但非单调的组合收益序列。"""
    return pd.Series([0.010, -0.006, 0.004, -0.002, 0.008, 0.003])


def sample_weights() -> dict[str, float]:
    """构造测试用目标权重。"""
    return {"AAA": 0.30, "BBB": 0.25, "CCC": 0.20, "DDD": 0.15}


def sample_market() -> pd.DataFrame:
    """构造带成交额和行业的市场约束数据。"""
    return pd.DataFrame(
        [
            {"symbol": "AAA", "amount": 2_000_000.0, "industry": "Tech"},
            {"symbol": "BBB", "amount": 300_000.0, "industry": "Tech"},
            {"symbol": "CCC", "amount": 1_000_000.0, "industry": "Finance"},
            {"symbol": "DDD", "amount": 80_000.0, "industry": "Energy"},
        ]
    )


class TestCapitalScalingAnalysis(unittest.TestCase):
    """验证 M5 只分析资金承载边界，不优化收益。"""

    def test_capital_scaling_simulator_outputs_required_metrics(self):
        """资金规模模拟必须输出收益、回撤、换手和执行成本。"""
        simulator = CapitalScalingSimulator(scales=[100_000, 500_000, 1_000_000, 5_000_000])

        results = simulator.simulate(sample_returns(), sample_weights(), sample_market(), turnover=0.40)

        self.assertEqual([item.capital for item in results], [100_000, 500_000, 1_000_000, 5_000_000])
        self.assertTrue(all(item.total_return != 0 for item in results))
        self.assertTrue(all(item.max_drawdown <= 0 for item in results))
        self.assertTrue(all(item.turnover == 0.40 for item in results))
        self.assertGreater(results[-1].execution_cost, results[0].execution_cost)

    def test_liquidity_stress_test_reports_untradable_ratio_and_failure_rate(self):
        """流动性压力测试必须输出不可交易比例和成交失败率。"""
        tester = LiquidityStressTester(max_amount_participation=0.10)

        result = tester.run(capital=1_000_000, weights=sample_weights(), market_data=sample_market())

        self.assertGreater(result.untradable_ratio, 0)
        self.assertGreater(result.execution_failure_rate, 0)
        self.assertIn("DDD", result.untradable_symbols)

    def test_execution_cost_curve_detects_scaling_break_point(self):
        """执行成本曲线需要判断资金规模是否出现非线性 break point。"""
        curve = ExecutionCostCurve()

        result = curve.analyze(
            capitals=[100_000, 500_000, 1_000_000, 5_000_000],
            execution_costs=[100.0, 700.0, 1_800.0, 20_000.0],
        )

        self.assertEqual(result.shape, "NON_LINEAR")
        self.assertEqual(result.break_point, 5_000_000)
        self.assertGreater(result.cost_bps_by_capital[5_000_000], result.cost_bps_by_capital[100_000])

    def test_portfolio_fragility_test_outputs_drawdown_change_and_recovery_time(self):
        """脆弱性测试需要覆盖单标的、行业集中和市场极端波动。"""
        tester = PortfolioFragilityTester()

        result = tester.run(
            returns=sample_returns(),
            weights=sample_weights(),
            industry_map={"AAA": "Tech", "BBB": "Tech", "CCC": "Finance", "DDD": "Energy"},
            shock_symbol="AAA",
            shock_industry="Tech",
        )

        self.assertEqual(set(result), {"single_symbol", "industry", "market_extreme"})
        self.assertLess(result["single_symbol"].stressed_max_drawdown, result["single_symbol"].base_max_drawdown)
        self.assertGreaterEqual(result["industry"].recovery_time, 0)

    def test_scaling_stability_analyzes_turnover_holdings_and_signal_consistency(self):
        """规模稳定性需要分析换手稳定、头部持仓稳定和信号一致性。"""
        analyzer = ScalingStabilityAnalyzer()

        result = analyzer.analyze(
            turnover_by_scale={100_000: 0.30, 500_000: 0.32, 1_000_000: 0.35, 5_000_000: 0.55},
            holdings_by_scale={
                100_000: ["AAA", "BBB", "CCC"],
                500_000: ["AAA", "BBB", "CCC"],
                1_000_000: ["AAA", "BBB", "DDD"],
                5_000_000: ["AAA", "EEE", "FFF"],
            },
            signals_by_scale={
                100_000: {"AAA": 1.0, "BBB": 0.8},
                500_000: {"AAA": 1.0, "BBB": 0.8},
                1_000_000: {"AAA": 0.9, "BBB": 0.7},
                5_000_000: {"AAA": 0.4, "EEE": 0.9},
            },
        )

        self.assertGreater(result.turnover_instability, 0)
        self.assertLess(result.top_holdings_stability, 1.0)
        self.assertLess(result.signal_consistency, 1.0)


if __name__ == "__main__":
    unittest.main()
