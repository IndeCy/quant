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


def test_due_orders_sell_before_buy_to_release_rebalance_cash(tmp_path: Path) -> None:
    """同日换仓即使买单先创建，也必须先卖出旧持仓释放现金。"""
    broker = LocalPaperBroker(tmp_path / "paper.sqlite3")
    account_id = broker.store.create_account(
        strategy_name="主线链动因子 V1",
        strategy_code="mainline_chain_factor_v1",
        initial_cash=110_000.0,
        benchmark_symbol="000001.SH",
        benchmark_name="上证指数",
        start_date="2026-07-08",
    )
    old_order_id = broker.store.record_pending_order(
        account_id, "2026-07-08", "OLD.SZ", "旧持仓", "BUY", 10.0, 9_000, "seed"
    )
    broker.store.fill_order(old_order_id, "2026-07-08", 10.0)
    broker.store.record_pending_order(
        account_id, "2026-07-09", "NEW.SZ", "新持仓", "BUY", 20.0, 5_000, "signal=2026-07-08"
    )
    broker.store.record_pending_order(
        account_id, "2026-07-09", "OLD.SZ", "旧持仓", "SELL", 10.0, 9_000, "signal=2026-07-08"
    )
    market = pd.DataFrame(
        [
            _execution_bar("OLD.SZ", 10.0),
            _execution_bar("NEW.SZ", 20.0),
        ]
    )

    executed, rejected = broker.execute_due_orders("20260709", market)
    orders = broker.store.list_orders(account_id)
    positions = broker.store.list_positions(account_id)

    assert executed == 2
    assert rejected == 0
    assert all(order["status"] == "FILLED" for order in orders)
    assert [(item["symbol"], item["quantity"]) for item in positions] == [("NEW.SZ", 5_000)]


def test_insufficient_cash_rejects_one_order_without_aborting_batch(tmp_path: Path) -> None:
    """一笔买单资金不足时应拒单，后续可成交委托仍需继续。"""
    broker = LocalPaperBroker(tmp_path / "paper.sqlite3")
    account_id = broker.store.create_account(
        strategy_name="测试策略",
        strategy_code="cash_guard_test",
        initial_cash=100_000.0,
        benchmark_symbol="510300.SH",
        benchmark_name="沪深300ETF",
        start_date="2026-07-08",
    )
    broker.store.record_pending_order(
        account_id, "2026-07-09", "TOO_BIG.SZ", "超额买单", "BUY", 10.0, 20_000, "signal=2026-07-08"
    )
    broker.store.record_pending_order(
        account_id, "2026-07-09", "VALID.SZ", "正常买单", "BUY", 10.0, 1_000, "signal=2026-07-08"
    )
    market = pd.DataFrame(
        [
            _execution_bar("TOO_BIG.SZ", 10.0),
            _execution_bar("VALID.SZ", 10.0),
        ]
    )

    executed, rejected = broker.execute_due_orders("20260709", market)
    orders = {order["symbol"]: order for order in broker.store.list_orders(account_id)}

    assert executed == 1
    assert rejected == 1
    assert orders["TOO_BIG.SZ"]["status"] == "REJECTED"
    assert orders["TOO_BIG.SZ"]["reject_reason"] == "INSUFFICIENT_CASH"
    assert orders["VALID.SZ"]["status"] == "FILLED"


def _execution_bar(symbol: str, open_price: float) -> dict[str, object]:
    """构造具备充足流动性的统一开盘行情。"""
    return {
        "trade_date": "20260709",
        "symbol": symbol,
        "name": symbol,
        "open": open_price,
        "close": open_price,
        "volume": 1_000_000,
        "is_suspended": False,
        "limit_up": False,
        "limit_down": False,
    }
