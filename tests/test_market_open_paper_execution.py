"""开盘本地模拟撮合测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.paper_trading import PaperTradingStore
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.market_open_paper_execution import run_market_open_paper_execution
from runtime.paths import RuntimePaths
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository
from runtime.risk_confirmation import PROCEED_DECISION, REDUCE_DECISION, record_risk_confirmation
from runtime.risk_policy import RiskPolicyRepository


def test_market_open_execution_fills_pending_orders_with_realtime_quotes(tmp_path: Path, monkeypatch) -> None:
    """早盘任务应只处理已有 PENDING 单，并按实时行情更新持仓。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account_id = store.create_account(
            strategy_name="Quality Alpha",
            strategy_code="quality_overlay",
            initial_cash=100_000.0,
            benchmark_symbol="510300",
            benchmark_name="沪深300",
            start_date="2026-07-09",
        )
        store.record_pending_order(
            account_id=account_id,
            order_date="2026-07-10",
            symbol="000001.SZ",
            symbol_name="平安银行",
            side="BUY",
            price=10.0,
            quantity=1000,
            note="local_paper_broker signal=2026-07-09",
        )
    finally:
        store.close()
    SystemRepository(paths.system_state_path).upsert_account_snapshot(
        build_account_snapshot(
            strategy_id="quality_overlay",
            trade_date="20260709",
            total_value=100_000.0,
            cash=100_000.0,
            target_weights={"000001.SZ": 0.1},
            actual_positions={},
        )
    )

    monkeypatch.setattr(
        "runtime.market_open_paper_execution.fetch_realtime_market_data",
        lambda symbols, trade_date=None: pd.DataFrame(
            [
                {
                    "trade_date": "20260710",
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "open": 10.2,
                    "high": 10.3,
                    "low": 10.1,
                    "close": 10.2,
                    "volume": 100_000,
                    "amount": 1_020_000,
                    "is_suspended": False,
                    "limit_up": False,
                    "limit_down": False,
                }
            ]
        ),
    )

    result = run_market_open_paper_execution(paths, trade_date="20260710", push=False)
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        orders = store.list_orders(account_id)
        positions = store.list_positions(account_id)
    finally:
        store.close()

    assert result.status == "SUCCESS"
    assert result.executed_orders == 1
    assert orders[0]["status"] == "FILLED"
    assert orders[0]["fill_date"] == "2026-07-10"
    assert positions[0]["symbol"] == "000001.SZ"
    account_snapshot = SystemRepository(paths.system_state_path).load_account_snapshot("quality_overlay")
    assert account_snapshot is not None
    assert account_snapshot["trade_date"] == "20260710"
    assert account_snapshot["positions"][0]["quantity"] == 1000
    assert account_snapshot["positions"][0]["target_weight"] == 0.1


def test_market_open_execution_waits_for_risk_confirmation(tmp_path: Path, monkeypatch) -> None:
    """上一交易日触发风险时，未确认不得撮合，明确允许后才放行。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动因子 V1",
            strategy_code="mainline_chain_factor_v1",
            initial_cash=100_000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-07-17",
        )
        store.record_pending_order(
            account_id, "2026-07-20", "000001.SZ", "平安银行", "BUY", 10.0, 1_000, "signal=2026-07-17"
        )
    finally:
        store.close()
    _seed_risk_metrics(paths)

    blocked = run_market_open_paper_execution(paths, trade_date="20260720", push=False)
    assert blocked.status == "BLOCKED"
    assert blocked.blocked_orders == 1
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        assert store.list_orders(account_id)[0]["status"] == "PENDING"
    finally:
        store.close()

    record_risk_confirmation(paths, "mainline_chain_factor_v1", "20260720", PROCEED_DECISION)
    monkeypatch.setattr(
        "runtime.market_open_paper_execution.fetch_realtime_market_data",
        lambda symbols, trade_date=None: pd.DataFrame(
            [
                {
                    "trade_date": "20260720",
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.0,
                    "volume": 100_000,
                    "amount": 1_000_000,
                    "is_suspended": False,
                    "limit_up": False,
                    "limit_down": False,
                }
            ]
        ),
    )

    allowed = run_market_open_paper_execution(paths, trade_date="20260720", push=False)
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        assert store.list_orders(account_id)[0]["status"] == "FILLED"
    finally:
        store.close()
    assert allowed.status == "SUCCESS"
    assert allowed.executed_orders == 1


def test_market_open_execution_replaces_original_orders_with_risk_reduction(tmp_path: Path, monkeypatch) -> None:
    """风险减仓应取消原策略单，并通过 Broker 等比例卖出到建议仓位。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动因子 V1",
            strategy_code="mainline_chain_factor_v1",
            initial_cash=100_000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-07-17",
        )
        seed_order_id = store.record_pending_order(
            account_id, "2026-07-17", "000001.SZ", "平安银行", "BUY", 10.0, 8_000, "seed"
        )
        store.fill_order(seed_order_id, "2026-07-17", 10.0)
        store.record_pending_order(
            account_id, "2026-07-20", "000001.SZ", "平安银行", "BUY", 10.0, 1_000, "signal=2026-07-17"
        )
    finally:
        store.close()
    _seed_risk_metrics(paths)
    record_risk_confirmation(paths, "mainline_chain_factor_v1", "20260720", REDUCE_DECISION)
    monkeypatch.setattr(
        "runtime.market_open_paper_execution.fetch_realtime_market_data",
        lambda symbols, trade_date=None: pd.DataFrame(
            [
                {
                    "trade_date": "20260720",
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.0,
                    "volume": 1_000_000,
                    "amount": 10_000_000,
                    "is_suspended": False,
                    "limit_up": False,
                    "limit_down": False,
                }
            ]
        ),
    )

    result = run_market_open_paper_execution(paths, trade_date="20260720", push=False)
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        orders = store.list_orders(account_id)
        positions = store.list_positions(account_id)
    finally:
        store.close()

    original_order = next(order for order in orders if order["side"] == "BUY" and order["order_date"] == "2026-07-20")
    reduction_order = next(order for order in orders if "risk_reduction" in str(order["note"]))
    assert result.status == "SUCCESS"
    assert result.cancelled_orders == 1
    assert result.risk_reduction_orders == 1
    assert result.executed_orders == 1
    assert original_order["status"] == "CANCELLED"
    assert original_order["reject_reason"] == "RISK_REDUCTION_OVERRIDE"
    assert reduction_order["side"] == "SELL"
    assert reduction_order["quantity"] == 5_000
    assert reduction_order["status"] == "FILLED"
    assert positions[0]["quantity"] == 3_000


def test_market_open_risk_reduction_runs_without_original_rebalance_order(tmp_path: Path, monkeypatch) -> None:
    """即使没有原调仓单，已确认风险减仓也必须主动生成并撮合卖单。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动因子 V1",
            strategy_code="mainline_chain_factor_v1",
            initial_cash=100_000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-07-17",
        )
        seed_order_id = store.record_pending_order(
            account_id, "2026-07-17", "000001.SZ", "平安银行", "BUY", 10.0, 5_000, "seed"
        )
        store.fill_order(seed_order_id, "2026-07-17", 10.0)
    finally:
        store.close()
    _seed_risk_metrics(paths)
    record_risk_confirmation(paths, "mainline_chain_factor_v1", "20260720", REDUCE_DECISION)
    monkeypatch.setattr(
        "runtime.market_open_paper_execution.fetch_realtime_market_data",
        lambda symbols, trade_date=None: pd.DataFrame([_market_open_bar("000001.SZ", 10.0)]),
    )

    result = run_market_open_paper_execution(paths, trade_date="20260720", push=False)
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        positions = store.list_positions(account_id)
        risk_orders = [order for order in store.list_orders(account_id) if "risk_reduction" in str(order["note"])]
    finally:
        store.close()

    assert result.pending_orders == 0
    assert result.risk_reduction_orders == 1
    assert result.executed_orders == 1
    assert risk_orders[0]["quantity"] == 2_000
    assert risk_orders[0]["status"] == "FILLED"
    assert positions[0]["quantity"] == 3_000


def test_active_risk_cap_allows_next_day_compliant_top_up_without_reconfirmation(tmp_path: Path, monkeypatch) -> None:
    """持续上限已在规划阶段生效时，次日合规补仓单不得再次被减仓流程取消。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        account_id = store.create_account(
            "主线链动因子 V1", "mainline_chain_factor_v1", 100_000.0, "000001.SH", "上证指数", "2026-07-17"
        )
        seed_order = store.record_pending_order(
            account_id, "2026-07-17", "000001.SZ", "平安银行", "BUY", 10.0, 2_000, "seed"
        )
        store.fill_order(seed_order, "2026-07-17", 10.0)
        store.record_pending_order(
            account_id, "2026-07-21", "000001.SZ", "平安银行", "BUY", 10.0, 1_000, "signal=2026-07-20"
        )
    finally:
        store.close()
    _seed_risk_metrics(paths)
    RiskPolicyRepository(paths.system_state_path).activate("mainline_chain_factor_v1", "20260720", 0.3)
    monkeypatch.setattr(
        "runtime.market_open_paper_execution.fetch_realtime_market_data",
        lambda symbols, trade_date=None: pd.DataFrame(
            [{**_market_open_bar("000001.SZ", 10.0), "trade_date": "20260721"}]
        ),
    )

    result = run_market_open_paper_execution(paths, trade_date="20260721", push=False)
    store = PaperTradingStore(paths.paper_trading_path)
    try:
        orders = store.list_orders(account_id)
        positions = store.list_positions(account_id)
    finally:
        store.close()

    compliant_buy = next(order for order in orders if order["order_date"] == "2026-07-21" and order["side"] == "BUY")
    assert result.blocked_orders == 0
    assert result.cancelled_orders == 0
    assert result.risk_reduction_orders == 0
    assert result.executed_orders == 1
    assert compliant_buy["status"] == "FILLED"
    assert positions[0]["quantity"] == 3_000


def _seed_risk_metrics(paths: RuntimePaths) -> None:
    dates = pd.to_datetime(["2026-07-16", "2026-07-17"])
    frame = build_strategy_monitor_frame(
        strategy_id="mainline_chain_factor_v1",
        strategy_name="主线链动因子 V1",
        daily_values=pd.Series([100.0, 91.0], index=dates),
        benchmark_values=pd.Series([1.0, 1.0], index=dates),
        exposure=pd.Series([1.0, 0.95], index=dates),
    )
    frame.loc[frame.index[-1], "daily_return"] = -0.09
    frame.loc[frame.index[-1], "drawdown"] = -0.21
    frame.loc[frame.index[-1], "volatility_20"] = 0.55
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)


def _market_open_bar(symbol: str, price: float) -> dict[str, object]:
    """构造可成交的开盘行情。"""
    return {
        "trade_date": "20260720",
        "symbol": symbol,
        "name": "平安银行",
        "open": price,
        "high": price * 1.01,
        "low": price * 0.99,
        "close": price,
        "volume": 1_000_000,
        "amount": 10_000_000,
        "is_suspended": False,
        "limit_up": False,
        "limit_down": False,
    }
