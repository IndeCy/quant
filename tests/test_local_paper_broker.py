"""统一本地 Paper Broker 测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from runtime.local_paper_broker import LocalPaperBroker, PaperBrokerTarget
from runtime.local_paper_bridge import next_broker_trading_dates


def _market_data() -> pd.DataFrame:
    """构造两日行情，模拟盘必须 T 日出信号、T+1 才成交。"""
    return pd.DataFrame(
        [
            {
                "trade_date": "20260708",
                "symbol": "AAA.SZ",
                "name": "甲股票",
                "open": 9.8,
                "close": 10.0,
                "volume": 100_000,
                "is_suspended": False,
                "limit_up": False,
                "limit_down": False,
            },
            {
                "trade_date": "20260709",
                "symbol": "AAA.SZ",
                "name": "甲股票",
                "open": 10.2,
                "close": 10.3,
                "volume": 100_000,
                "is_suspended": False,
                "limit_up": False,
                "limit_down": False,
            },
        ]
    )


def test_local_paper_broker_creates_t1_pending_orders(tmp_path: Path) -> None:
    """策略目标权重进入统一 Broker 后，只能生成下一交易日委托。"""
    broker = LocalPaperBroker(tmp_path / "paper.sqlite3")

    result = broker.sync_target(
        PaperBrokerTarget(
            strategy_id="quality_overlay",
            strategy_name="Quality Alpha",
            trade_date="20260708",
            target_weights={"AAA.SZ": 0.5},
            market_data=_market_data(),
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )

    orders = broker.store.list_orders(result.account_id)

    assert result.created_orders == 1
    assert result.executed_orders == 0
    assert orders[0]["status"] == "PENDING"
    assert orders[0]["order_date"] == "2026-07-09"
    assert orders[0]["symbol"] == "AAA.SZ"


def test_local_paper_broker_executes_due_orders_and_updates_positions(tmp_path: Path) -> None:
    """T+1 运行同一入口时，应撮合昨日委托并更新统一持仓。"""
    broker = LocalPaperBroker(tmp_path / "paper.sqlite3")
    broker.sync_target(
        PaperBrokerTarget(
            strategy_id="mainline_chain_factor_v1",
            strategy_name="主线链动因子 V1",
            trade_date="20260708",
            target_weights={"AAA.SZ": 0.5},
            market_data=_market_data(),
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )

    result = broker.sync_target(
        PaperBrokerTarget(
            strategy_id="mainline_chain_factor_v1",
            strategy_name="主线链动因子 V1",
            trade_date="20260709",
            target_weights={"AAA.SZ": 0.5},
            market_data=_market_data(),
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )
    orders = broker.store.list_orders(result.account_id)
    positions = broker.store.list_positions(result.account_id)

    assert result.executed_orders == 1
    assert orders[0]["status"] == "FILLED"
    assert orders[0]["fill_date"] == "2026-07-09"
    assert positions[0]["symbol"] == "AAA.SZ"
    assert positions[0]["quantity"] > 0


def test_next_broker_trading_dates_uses_calendar_for_future_order_date() -> None:
    """盘后行情没有明日数据时，也必须能按交易日历生成 T+1 委托日期。"""
    dates = next_broker_trading_dates("20260710")

    assert dates == ["20260710", "20260713"]
