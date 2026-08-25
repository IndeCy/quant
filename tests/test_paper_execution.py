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
        "limit_up": False,
        "limit_down": False,
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
                {"date": "2024-01-03", "symbol": "AAA", "open": 11.0, "close": 11.0, "limit_up": True},
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

    def test_multi_asset_rebalance_uses_complete_portfolio_value(self):
        """二次调仓必须按全部持仓市值计算目标，而不是逐票漏估。"""
        rows = []
        for date, aaa_close in [
            ("2024-01-02", 10.0),
            ("2024-01-03", 10.0),
            ("2024-01-04", 20.0),
            ("2024-01-05", 20.0),
        ]:
            rows.extend(
                [
                    {
                        "date": date,
                        "symbol": "AAA",
                        "open": aaa_close,
                        "close": aaa_close,
                    },
                    {
                        "date": date,
                        "symbol": "BBB",
                        "open": 10.0,
                        "close": 10.0,
                    },
                ]
            )
        broker = BrokerSimulator(BrokerConfig(slippage_bps=0))
        engine = PaperTradingEngine(initial_cash=10_000.0, broker=broker)

        result = engine.run_signals(
            {
                "2024-01-02": {"AAA": 0.50, "BBB": 0.50},
                "2024-01-04": {"AAA": 0.50, "BBB": 0.50},
            },
            market_frame(rows),
        )
        signal_snapshot = next(
            item for item in result.snapshots if item.date == "2024-01-04"
        )

        self.assertEqual(signal_snapshot.total_value, 15_000.0)
        self.assertEqual(signal_snapshot.target_holdings, {"AAA": 375, "BBB": 750})
        self.assertEqual(len(result.snapshots), 4)

    def test_open_aware_replay_sizes_target_with_t1_open_price(self):
        """历史Paper启用新政策后，应在T+1按开盘价重算目标股数。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "AAA", "close": 10.0},
                {"date": "2024-01-02", "symbol": "BBB", "close": 10.0},
                {
                    "date": "2024-01-03",
                    "symbol": "AAA",
                    "open": 10.5,
                    "close": 10.5,
                },
                {
                    "date": "2024-01-03",
                    "symbol": "BBB",
                    "open": 10.5,
                    "close": 10.5,
                },
            ]
        )
        broker = BrokerSimulator(
            BrokerConfig(
                slippage_bps=10.0,
                max_participation_rate=1.0,
                commission_rate=0.0003,
                min_commission=5.0,
                lot_size=100,
                open_aware_order_sizing=True,
            )
        )

        result = PaperTradingEngine(
            initial_cash=100_000.0,
            broker=broker,
        ).run_signals(
            {"2024-01-02": {"AAA": 0.5, "BBB": 0.5}},
            data,
        )

        self.assertEqual(
            sorted(order.quantity for order in result.orders),
            [4_700, 4_700],
        )
        self.assertTrue(all(order.status == "FILLED" for order in result.orders))
        self.assertEqual(
            result.snapshots[-1].target_holdings,
            {"AAA": 4_700, "BBB": 4_700},
        )

    def test_open_aware_replay_retries_only_missing_symbol(self):
        """单票T+1缺价时其他股票照常成交，缺价票在T+2重试。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "AAA", "close": 10.0},
                {"date": "2024-01-02", "symbol": "BBB", "close": 10.0},
                {
                    "date": "2024-01-03",
                    "symbol": "AAA",
                    "open": 10.0,
                    "close": 10.0,
                },
                {
                    "date": "2024-01-03",
                    "symbol": "BBB",
                    "open": 0.0,
                    "close": 10.0,
                    "is_suspended": True,
                },
                {
                    "date": "2024-01-04",
                    "symbol": "AAA",
                    "open": 10.0,
                    "close": 10.0,
                },
                {
                    "date": "2024-01-04",
                    "symbol": "BBB",
                    "open": 0.0,
                    "close": 10.0,
                    "is_suspended": True,
                },
                {
                    "date": "2024-01-05",
                    "symbol": "AAA",
                    "open": 10.0,
                    "close": 10.0,
                },
                {
                    "date": "2024-01-05",
                    "symbol": "BBB",
                    "open": 10.0,
                    "close": 10.0,
                },
            ]
        )
        broker = BrokerSimulator(
            BrokerConfig(
                slippage_bps=0.0,
                max_participation_rate=1.0,
                lot_size=100,
                open_aware_order_sizing=True,
            )
        )

        result = PaperTradingEngine(
            initial_cash=100_000.0,
            broker=broker,
        ).run_signals(
            {"2024-01-02": {"AAA": 0.5, "BBB": 0.5}},
            data,
        )
        day_two = next(
            item for item in result.snapshots if item.date == "2024-01-03"
        )
        bbb_order = next(
            order for order in result.orders if order.symbol == "BBB"
        )

        self.assertGreater(day_two.actual_holdings.get("AAA", 0), 0)
        self.assertEqual(day_two.actual_holdings.get("BBB", 0), 0)
        self.assertEqual(bbb_order.execute_date, "2024-01-05")
        self.assertEqual(bbb_order.status, "FILLED")
        self.assertEqual(
            sum(order.symbol == "AAA" for order in result.orders),
            1,
        )
        self.assertGreater(result.snapshots[-1].actual_holdings["BBB"], 0)

    def test_open_aware_new_target_removes_stale_unfilled_symbol(self):
        """新目标必须清除上期已落选但未成交的幽灵目标。"""
        data = market_frame(
            [
                {"date": "2024-01-02", "symbol": "BBB", "close": 10.0},
                {
                    "date": "2024-01-03",
                    "symbol": "AAA",
                    "open": 10.0,
                    "close": 10.0,
                },
                {
                    "date": "2024-01-03",
                    "symbol": "BBB",
                    "open": 10.0,
                    "close": 10.0,
                    "limit_up": True,
                },
                {
                    "date": "2024-01-04",
                    "symbol": "AAA",
                    "open": 10.0,
                    "close": 10.0,
                },
                {
                    "date": "2024-01-04",
                    "symbol": "BBB",
                    "open": 10.0,
                    "close": 10.0,
                },
            ]
        )
        broker = BrokerSimulator(
            BrokerConfig(
                slippage_bps=0.0,
                max_participation_rate=1.0,
                lot_size=100,
                open_aware_order_sizing=True,
            )
        )

        result = PaperTradingEngine(
            initial_cash=100_000.0,
            broker=broker,
        ).run_signals(
            {
                "2024-01-02": {"BBB": 1.0},
                "2024-01-03": {"AAA": 1.0},
            },
            data,
        )

        self.assertEqual(result.orders[0].status, "REJECTED")
        self.assertNotIn("BBB", result.snapshots[-1].target_holdings)
        self.assertGreater(
            result.snapshots[-1].actual_holdings.get("AAA", 0),
            0,
        )

    def test_paper_execution_applies_cash_and_asset_tax_constraints(self):
        """买入不得透支，卖出股票收税而ETF免税。"""
        config = BrokerConfig(
            slippage_bps=0,
            commission_rate=0.001,
            stamp_tax_rate=0.001,
            min_commission=5.0,
            tax_exempt_symbols=frozenset({"ETF"}),
        )
        broker = BrokerSimulator(config)
        manager = OrderManager()
        buy = manager.create_order(
            "2024-01-02",
            "2024-01-03",
            "AAA",
            "BUY",
            1_000,
            10.0,
        )

        filled = broker.execute(
            buy,
            market_frame(
                [{"date": "2024-01-03", "symbol": "AAA"}]
            ).iloc[0],
            manager,
            cash_available=1_000.0,
        )

        self.assertEqual(filled.status, "PARTIAL_FILLED")
        self.assertLessEqual(
            filled.fill_price * filled.filled_quantity
            + manager.execution_logs[-1].commission,
            1_000.0,
        )
        stock_sell = manager.create_order(
            "2024-01-02", "2024-01-03", "AAA", "SELL", 100, 10.0
        )
        etf_sell = manager.create_order(
            "2024-01-02", "2024-01-03", "ETF", "SELL", 100, 10.0
        )
        row = market_frame(
            [{"date": "2024-01-03", "symbol": "AAA"}]
        ).iloc[0]
        broker.execute(stock_sell, row, manager)
        broker.execute(etf_sell, row, manager)

        self.assertGreater(manager.execution_logs[-2].stamp_tax, 0)
        self.assertEqual(manager.execution_logs[-1].stamp_tax, 0)


if __name__ == "__main__":
    unittest.main()
