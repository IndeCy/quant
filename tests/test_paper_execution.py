"""
Milestone 3 Paper Trading / Shadow Trading 执行仿真测试。
"""

from __future__ import annotations

import unittest

import pandas as pd

from backtest.paper_execution import (
    BrokerConfig,
    BrokerSimulator,
    DriftAnalyzer,
    OrderManager,
    PaperTradingEngine,
    PortfolioTracker,
)


def market_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """构造测试用行情表。"""
    defaults = {
        "open": 10.0,
        "close": 10.0,
        "volume": 100_000,
        "is_suspended": False,
        "limit_up": 11.0,
        "limit_down": 9.0,
    }
    normalized = []
    for row in rows:
        item = defaults | row
        normalized.append(item)
    return pd.DataFrame(normalized)


class TestPaperExecution(unittest.TestCase):
    """验证模拟盘不是 position=signal，而是 signal→order→execution→portfolio。"""

    def test_signal_delay_test_executes_on_next_trading_day(self):
        """T 日信号默认只能在 T+1 交易日成交。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "AAA", "close": 10.0},
                {"date": "2024-01-03", "symbol": "AAA", "open": 10.2, "close": 10.3},
            ]
        )
        engine = PaperTradingEngine(initial_cash=10_000.0)

        result = engine.run_signals({"2024-01-02": {"AAA": 0.50}}, data)

        self.assertEqual(result.orders[0].status, "FILLED")
        self.assertEqual(result.orders[0].signal_date, "2024-01-02")
        self.assertEqual(result.orders[0].execute_date, "2024-01-03")
        self.assertGreater(result.snapshots[-1].actual_holdings["AAA"], 0)

    def test_execution_failure_test_rejects_limit_up_buy(self):
        """买入遇到涨停时不成交，并记录 rejected。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "AAA", "close": 10.0},
                {"date": "2024-01-03", "symbol": "AAA", "open": 11.0, "close": 11.0, "limit_up": 11.0},
            ]
        )
        engine = PaperTradingEngine(initial_cash=10_000.0)

        result = engine.run_signals({"2024-01-02": {"AAA": 0.50}}, data)

        self.assertEqual(result.orders[0].status, "REJECTED")
        self.assertEqual(result.orders[0].reject_reason, "LIMIT_UP_NO_FILL")
        self.assertEqual(result.snapshots[-1].actual_holdings.get("AAA", 0), 0)

    def test_slippage_sensitivity_test_changes_execution_price_and_impact(self):
        """滑点越高，买入成交价越高，执行冲击越大。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "AAA", "close": 10.0},
                {"date": "2024-01-03", "symbol": "AAA", "open": 10.0, "close": 10.0},
            ]
        )
        low = BrokerSimulator(BrokerConfig(slippage_bps=0))
        high = BrokerSimulator(BrokerConfig(slippage_bps=100))
        low_result = PaperTradingEngine(initial_cash=10_000.0, broker=low).run_signals(
            {"2024-01-02": {"AAA": 0.50}},
            data,
        )
        high_result = PaperTradingEngine(initial_cash=10_000.0, broker=high).run_signals(
            {"2024-01-02": {"AAA": 0.50}},
            data,
        )

        self.assertGreater(high_result.executions[0].fill_price, low_result.executions[0].fill_price)
        self.assertGreater(high_result.executions[0].execution_impact, low_result.executions[0].execution_impact)

    def test_backtest_vs_paper_comparison_reports_tracking_error(self):
        """模拟盘因延迟和滑点产生的净值差异，应能形成 tracking error。"""
        paper_curve = pd.Series([1.0, 1.0, 1.01, 1.008])
        backtest_curve = pd.Series([1.0, 1.01, 1.02, 1.018])

        metrics = DriftAnalyzer().compare_curves(backtest_curve, paper_curve)

        self.assertIn("tracking_error", metrics)
        self.assertGreater(metrics["tracking_error"], 0)
        self.assertLess(metrics["paper_total_return"], metrics["backtest_total_return"])

    def test_tracking_error_does_not_return_nan_for_single_difference(self):
        """只有一段收益差时，tracking error 也不能返回 NaN。"""
        metrics = DriftAnalyzer().compare_curves(pd.Series([1.0, 1.02]), pd.Series([1.0, 1.01]))

        self.assertEqual(metrics["tracking_error"], 0.0)

    def test_turnover_deviation_test_detects_partial_fill(self):
        """流动性约束导致部分成交时，实际换手应低于目标换手。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "AAA", "close": 10.0, "volume": 100},
                {"date": "2024-01-03", "symbol": "AAA", "open": 10.0, "close": 10.0, "volume": 100},
            ]
        )
        broker = BrokerSimulator(BrokerConfig(max_participation_rate=0.10))
        result = PaperTradingEngine(initial_cash=10_000.0, broker=broker).run_signals(
            {"2024-01-02": {"AAA": 1.00}},
            data,
        )

        metrics = DriftAnalyzer().compare_turnover(target_turnover=1.0, actual_turnover=result.actual_turnover)

        self.assertEqual(result.orders[0].status, "PARTIAL_FILLED")
        self.assertLess(result.actual_turnover, 1.0)
        self.assertGreater(metrics["turnover_deviation"], 0)

    def test_portfolio_tracker_reports_target_actual_drift_and_unrealized_pnl(self):
        """PortfolioTracker 需要同时记录实际持仓、目标持仓、漂移和浮动盈亏。"""
        tracker = PortfolioTracker(initial_cash=1_000.0)
        tracker.set_target_holdings({"AAA": 100})
        tracker.apply_fill(symbol="AAA", side="BUY", quantity=80, price=10.0, signal_price=10.0)

        snapshot = tracker.snapshot("2024-01-03", {"AAA": 11.0})

        self.assertEqual(snapshot.target_holdings["AAA"], 100)
        self.assertEqual(snapshot.actual_holdings["AAA"], 80)
        self.assertEqual(snapshot.drift["AAA"], -20)
        self.assertEqual(snapshot.unrealized_pnl["AAA"], 80.0)

    def test_order_manager_tracks_lifecycle_and_logs(self):
        """OrderManager 需要记录 pending、filled、rejected 及执行日志。"""
        manager = OrderManager()
        order = manager.create_order("2024-01-02", "2024-01-03", "AAA", "BUY", 100, 10.0)
        manager.mark_filled(order.order_id, 80, 10.1)
        rejected = manager.create_order("2024-01-02", "2024-01-03", "BBB", "BUY", 100, 10.0)
        manager.mark_rejected(rejected.order_id, "LIMIT_UP_NO_FILL")

        self.assertEqual(manager.orders[0].status, "PARTIAL_FILLED")
        self.assertEqual(manager.orders[1].status, "REJECTED")
        self.assertEqual(len(manager.execution_logs), 2)


if __name__ == "__main__":
    unittest.main()
