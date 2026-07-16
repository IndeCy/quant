"""开盘本地模拟撮合测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.paper_trading import PaperTradingStore
from runtime.market_open_paper_execution import run_market_open_paper_execution
from runtime.paths import RuntimePaths
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository


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
