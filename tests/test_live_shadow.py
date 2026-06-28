"""
Milestone 4 Small Capital Shadow Live System 测试。
"""

from __future__ import annotations

import unittest

import pandas as pd

from backtest.live_shadow import (
    CapitalConstraint,
    DailyReconciliation,
    LiveDataLoop,
    MarketConstraintChecker,
    PortfolioDriftSystem,
)


def market_data() -> pd.DataFrame:
    """构造 M4 测试用真实行情形态数据。"""
    return pd.DataFrame(
        [
            {
                "date": "2024-01-03",
                "symbol": "AAA",
                "open": 10.0,
                "close": 10.0,
                "volume": 100_000,
                "amount": 1_000_000.0,
                "is_suspended": False,
                "limit_up": 11.0,
                "limit_down": 9.0,
            },
            {
                "date": "2024-01-03",
                "symbol": "BBB",
                "open": 20.0,
                "close": 20.0,
                "volume": 1_000,
                "amount": 20_000.0,
                "is_suspended": False,
                "limit_up": 20.0,
                "limit_down": 18.0,
            },
            {
                "date": "2024-01-03",
                "symbol": "CCC",
                "open": 30.0,
                "close": 30.0,
                "volume": 50_000,
                "amount": 1_500_000.0,
                "is_suspended": True,
                "limit_up": 33.0,
                "limit_down": 27.0,
            },
        ]
    )


class TestSmallCapitalShadowLiveSystem(unittest.TestCase):
    """验证 M4 准实盘系统只做稳定性检查，不接真实券商下单。"""

    def test_daily_live_loop_generates_signal_target_and_rebalance_plan(self):
        """每日收盘后应更新数据、生成信号、目标组合和调仓计划。"""
        calls: list[str] = []

        def update_data(trade_date: str) -> pd.DataFrame:
            calls.append(f"update:{trade_date}")
            return market_data()

        def generate_signal(data: pd.DataFrame) -> dict[str, float]:
            calls.append("signal")
            return {"AAA": 0.60, "BBB": 0.30}

        def build_portfolio(signal: dict[str, float]) -> dict[str, float]:
            calls.append("portfolio")
            return signal

        loop = LiveDataLoop(
            data_updater=update_data,
            signal_generator=generate_signal,
            portfolio_builder=build_portfolio,
            capital_constraint=CapitalConstraint(capital=100_000.0, max_symbol_weight=0.50, min_cash_ratio=0.10),
        )

        result = loop.run_daily("2024-01-03", actual_weights={"AAA": 0.20})

        self.assertEqual(calls, ["update:2024-01-03", "signal", "portfolio"])
        self.assertEqual(result.trade_date, "2024-01-03")
        self.assertEqual(result.signal, {"AAA": 0.60, "BBB": 0.30})
        self.assertLessEqual(result.target_weights["AAA"], 0.50)
        self.assertGreater(result.rebalance_plan.total_buy_amount, 0)

    def test_market_constraints_detect_limit_suspend_liquidity_and_t1_pending(self):
        """约束检查必须识别涨停、停牌、流动性不足和 T+1 确认。"""
        checker = MarketConstraintChecker(max_amount_participation=0.10)
        plan = {
            "AAA": 50_000.0,
            "BBB": 50_000.0,
            "CCC": 10_000.0,
        }

        checks = checker.check_plan(plan, market_data(), side_by_symbol={"AAA": "BUY", "BBB": "BUY", "CCC": "BUY"})

        self.assertTrue(checks["AAA"].t1_confirmation_required)
        self.assertEqual(checks["BBB"].status, "BLOCKED")
        self.assertIn("LIMIT_UP_NO_FILL", checks["BBB"].reasons)
        self.assertIn("LIQUIDITY_LIMIT", checks["BBB"].reasons)
        self.assertEqual(checks["CCC"].status, "BLOCKED")
        self.assertIn("SUSPENDED_NO_FILL", checks["CCC"].reasons)

    def test_drift_control_triggers_rebalance_hint(self):
        """target 与 actual 偏离超过阈值时，应提示调仓。"""
        result = PortfolioDriftSystem(threshold=0.05).analyze(
            target_weights={"AAA": 0.50, "BBB": 0.40},
            actual_weights={"AAA": 0.35, "BBB": 0.45},
        )

        self.assertTrue(result.should_rebalance)
        self.assertAlmostEqual(result.max_abs_drift, 0.15)
        self.assertEqual(result.rebalance_symbols, ["AAA"])

    def test_daily_reconciliation_outputs_pnl_breakdown(self):
        """每日对账必须输出 paper、理论、执行和偏离拆解。"""
        result = DailyReconciliation().reconcile(
            previous_value=100_000.0,
            paper_value=101_000.0,
            theoretical_value=102_000.0,
            execution_cost=300.0,
            drift_cost=700.0,
        )

        self.assertAlmostEqual(result.paper_pnl, 1_000.0)
        self.assertAlmostEqual(result.theoretical_pnl, 2_000.0)
        self.assertAlmostEqual(result.execution_pnl, -300.0)
        self.assertAlmostEqual(result.deviation_breakdown["total_deviation"], -1_000.0)
        self.assertAlmostEqual(result.deviation_breakdown["drift_cost"], 700.0)

    def test_capital_constraint_applies_cash_and_single_position_limits(self):
        """固定资金规模下应限制单票仓位，并保留现金比例。"""
        constraint = CapitalConstraint(capital=100_000.0, max_symbol_weight=0.40, min_cash_ratio=0.10)

        result = constraint.apply({"AAA": 0.80, "BBB": 0.30})

        self.assertLessEqual(result.target_weights["AAA"], 0.40)
        self.assertLessEqual(sum(result.target_weights.values()), 0.90)
        self.assertGreaterEqual(result.cash_weight, 0.10)
        self.assertAlmostEqual(result.target_amounts["AAA"], 40_000.0)


if __name__ == "__main__":
    unittest.main()
