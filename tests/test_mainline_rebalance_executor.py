"""
测试主线链动策略次日调仓执行器。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.mainline_rebalance_executor import execute_due_rebalance
from backtest.paper_execution import BrokerConfig
from backtest.paper_trading import PaperTradingStore


def _make_trade_day_bar(trade_date: str, open_price: float, close_price: float, volume: float) -> pd.DataFrame:
    """构造单日行情，供执行器测试成交逻辑。"""
    index = pd.to_datetime([trade_date])
    return pd.DataFrame(
        {
            "open": [open_price],
            "high": [max(open_price, close_price)],
            "low": [min(open_price, close_price)],
            "close": [close_price],
            "volume": [volume],
            "amount": [0.0],
        },
        index=index,
    )


def _seed_switch_account(db_path: Path) -> int:
    """创建一个前一日已发出 SWITCH 的测试账户。"""
    store = PaperTradingStore(db_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=10000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-06-24",
        )
        order_id = store.record_pending_order(
            account_id=account_id,
            order_date="2026-06-24",
            symbol="A1",
            symbol_name="旧龙头",
            side="BUY",
            price=10.0,
            quantity=1000,
        )
        store.fill_order(order_id, "2026-06-25", 10.0)
        store.record_daily_snapshot(
            account_id=account_id,
            trade_date="2026-06-25",
            total_value=10000.0,
            cash=0.0,
            position_value=10000.0,
            strategy_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            strongest_chain="半导体",
            rebalance_signal="SWITCH",
            target_symbols=["B1"],
        )
        return account_id
    finally:
        store.close()


def test_execute_due_rebalance_switches_position_on_due_day(tmp_path: Path):
    """前一日已发 SWITCH 且次日未落单时，应自动卖旧买新。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = _seed_switch_account(db_path)
    market_bars = {
        "A1": _make_trade_day_bar("2026-06-26", 10.0, 10.0, 100000.0),
        "B1": _make_trade_day_bar("2026-06-26", 20.0, 20.0, 100000.0),
    }

    result = execute_due_rebalance(
        account_id=account_id,
        trade_date=date(2026, 6, 26),
        db_path=db_path,
        market_bars=market_bars,
        broker_config=BrokerConfig(slippage_bps=0.0, max_participation_rate=1.0),
    )

    store = PaperTradingStore(db_path)
    try:
        positions = store.list_positions(account_id)
        orders = store.list_orders(account_id)
    finally:
        store.close()

    assert result.executed is True
    assert result.created_orders == 2
    assert result.filled_orders == 2
    assert result.rejected_orders == 0
    assert len(positions) == 1
    assert positions[0]["symbol"] == "B1"
    assert positions[0]["quantity"] == 500
    assert orders[0]["status"] == "FILLED"
    assert orders[0]["filled_quantity"] > 0


def test_execute_due_rebalance_skips_when_trade_day_orders_exist(tmp_path: Path):
    """执行日已有委托时，不应重复补单。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = _seed_switch_account(db_path)
    store = PaperTradingStore(db_path)
    try:
        store.record_pending_order(
            account_id=account_id,
            order_date="2026-06-26",
            symbol="A1",
            symbol_name="旧龙头",
            side="SELL",
            price=10.0,
            quantity=1000,
        )
    finally:
        store.close()

    result = execute_due_rebalance(
        account_id=account_id,
        trade_date=date(2026, 6, 26),
        db_path=db_path,
        market_bars={"A1": _make_trade_day_bar("2026-06-26", 10.0, 10.0, 100000.0)},
        broker_config=BrokerConfig(slippage_bps=0.0, max_participation_rate=1.0),
    )

    assert result.executed is False
    assert result.reason == "ORDERS_ALREADY_EXIST"


def test_execute_due_rebalance_does_not_reject_buy_when_limit_up_flag_is_false(tmp_path: Path):
    """limit_up 为 False 时，买单不应被误判成涨停买不到。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = _seed_switch_account(db_path)
    market_bars = {
        "A1": _make_trade_day_bar("2026-06-26", 10.0, 10.0, 100000.0),
        "B1": _make_trade_day_bar("2026-06-26", 20.0, 20.0, 100000.0),
    }
    market_bars["B1"]["limit_up"] = [False]

    result = execute_due_rebalance(
        account_id=account_id,
        trade_date=date(2026, 6, 26),
        db_path=db_path,
        market_bars=market_bars,
        broker_config=BrokerConfig(slippage_bps=0.0, max_participation_rate=1.0),
    )

    assert result.rejected_orders == 0
