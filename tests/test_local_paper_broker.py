"""统一本地 Paper Broker 测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.paper_execution import BrokerConfig
from runtime.local_paper_broker import LocalPaperBroker, PaperBrokerTarget
from runtime.local_paper_bridge import next_broker_trading_dates
from runtime.paper_execution_policy import load_execution_policy


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
            execute_due_orders=True,
        )
    )
    orders = broker.store.list_orders(result.account_id)
    positions = broker.store.list_positions(result.account_id)

    assert result.executed_orders == 1
    assert orders[0]["status"] == "FILLED"
    assert orders[0]["fill_date"] == "2026-07-09"
    assert positions[0]["symbol"] == "AAA.SZ"
    assert positions[0]["quantity"] > 0


def test_target_sync_can_defer_due_orders_to_market_open_executor(tmp_path: Path) -> None:
    """盘后目标同步不得绕过开盘门禁成交旧委托，也不得叠加新订单。"""
    broker = LocalPaperBroker(tmp_path / "paper.sqlite3")
    first = broker.sync_target(
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

    second = broker.sync_target(
        PaperBrokerTarget(
            strategy_id="quality_overlay",
            strategy_name="Quality Alpha",
            trade_date="20260709",
            target_weights={"AAA.SZ": 0.7},
            market_data=_market_data(),
            trading_dates=["20260709", "20260710"],
            initial_cash=100_000.0,
            execute_due_orders=False,
        )
    )

    orders = broker.store.list_orders(first.account_id)
    assert second.executed_orders == 0
    assert second.created_orders == 0
    assert len(orders) == 1
    assert orders[0]["status"] == "PENDING"
    assert broker.store.list_positions(first.account_id) == []


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


def test_account_execution_policy_survives_market_open_restart(tmp_path: Path) -> None:
    """盘后保存的费率口径必须被次日独立开盘进程读取并真实入账。"""
    db_path = tmp_path / "paper.sqlite3"
    config = BrokerConfig(
        slippage_bps=100.0,
        execution_delay=1,
        max_participation_rate=1.0,
        commission_rate=0.01,
        stamp_tax_rate=0.02,
        min_commission=0.0,
        lot_size=100,
    )
    signal_broker = LocalPaperBroker(db_path, config)
    first = signal_broker.sync_target(
        PaperBrokerTarget(
            strategy_id="persisted_execution_policy",
            strategy_name="持久化执行口径测试",
            trade_date="20260708",
            target_weights={"AAA.SZ": 0.5},
            market_data=_market_data(),
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )
    signal_broker.close()

    persisted = load_execution_policy(db_path, first.account_id)
    assert persisted is not None
    assert persisted.slippage_bps == 100.0
    assert persisted.commission_rate == 0.01
    assert persisted.stamp_tax_rate == 0.02
    assert persisted.lot_size == 100

    open_broker = LocalPaperBroker(db_path)
    executed, rejected = open_broker.execute_due_orders(
        "20260709",
        _market_data(),
        [first.account_id],
    )
    buy_order = open_broker.store.list_orders(first.account_id)[0]
    account = open_broker.store.get_account(first.account_id)

    assert (executed, rejected) == (1, 0)
    assert buy_order["fill_price"] == 10.302
    assert buy_order["commission"] == 515.1
    assert buy_order["stamp_tax"] == 0.0
    assert float(account["cash"]) == pytest.approx(47_974.9)

    open_broker.sync_target(
        PaperBrokerTarget(
            strategy_id="persisted_execution_policy",
            strategy_name="持久化执行口径测试",
            trade_date="20260709",
            target_weights={},
            market_data=_market_data(),
            trading_dates=["20260709", "20260710"],
            initial_cash=100_000.0,
        )
    )
    open_broker.close()

    sell_broker = LocalPaperBroker(db_path)
    executed, rejected = sell_broker.execute_due_orders(
        "20260710",
        pd.DataFrame([_execution_bar("AAA.SZ", 10.0, "20260710")]),
        [first.account_id],
    )
    sell_order = next(
        item
        for item in sell_broker.store.list_orders(first.account_id)
        if item["side"] == "SELL"
    )
    account = sell_broker.store.get_account(first.account_id)

    assert (executed, rejected) == (1, 0)
    assert sell_order["fill_price"] == 9.9
    assert sell_order["commission"] == 495.0
    assert sell_order["stamp_tax"] == 990.0
    assert float(account["cash"]) == pytest.approx(95_989.9)
    assert sell_broker.store.list_positions(first.account_id) == []
    sell_broker.close()


def test_open_aware_policy_resizes_due_orders_with_t1_open_price(
    tmp_path: Path,
) -> None:
    """显式启用后应按T+1开盘价重建整手订单，避免隔夜高开整单拒绝。"""
    db_path = tmp_path / "paper.sqlite3"
    config = BrokerConfig(
        slippage_bps=10.0,
        execution_delay=1,
        max_participation_rate=1.0,
        commission_rate=0.0003,
        min_commission=5.0,
        lot_size=100,
        open_aware_order_sizing=True,
    )
    signal_market = pd.DataFrame(
        [
            _signal_bar("AAA.SZ", 10.0),
            _signal_bar("BBB.SZ", 10.0),
        ]
    )
    broker = LocalPaperBroker(db_path, config)
    synced = broker.sync_target(
        PaperBrokerTarget(
            strategy_id="open_aware_test",
            strategy_name="开盘重算测试",
            trade_date="20260708",
            target_weights={"AAA.SZ": 0.5, "BBB.SZ": 0.5},
            market_data=signal_market,
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )
    broker.close()

    open_market = pd.DataFrame(
        [
            _execution_bar("AAA.SZ", 10.5),
            _execution_bar("BBB.SZ", 10.5),
        ]
    )
    restarted = LocalPaperBroker(db_path)
    resize = restarted.resize_due_orders(
        synced.account_id,
        "20260709",
        open_market,
    )
    executed, rejected = restarted.execute_due_orders(
        "20260709",
        open_market,
        [synced.account_id],
    )
    orders = restarted.store.list_orders(synced.account_id)
    positions = restarted.store.list_positions(synced.account_id)
    restarted.close()

    assert resize.status == "RESIZED"
    assert resize.cancelled_orders == 2
    assert resize.created_orders == 2
    assert (executed, rejected) == (2, 0)
    assert sorted(
        order["quantity"]
        for order in orders
        if order["status"] == "FILLED"
    ) == [4_700, 4_700]
    assert sorted(item["quantity"] for item in positions) == [4_700, 4_700]


def test_open_aware_partial_resize_retries_missing_symbol(
    tmp_path: Path,
) -> None:
    """单票缺开盘价不得阻塞组合，未完成目标应在下一交易日重试。"""
    db_path = tmp_path / "paper.sqlite3"
    config = BrokerConfig(
        slippage_bps=0.0,
        execution_delay=1,
        max_participation_rate=1.0,
        lot_size=100,
        open_aware_order_sizing=True,
    )
    broker = LocalPaperBroker(db_path, config)
    synced = broker.sync_target(
        PaperBrokerTarget(
            strategy_id="open_aware_partial",
            strategy_name="开盘部分重算测试",
            trade_date="20260708",
            target_weights={"AAA.SZ": 0.5, "BBB.SZ": 0.5},
            market_data=pd.DataFrame(
                [
                    _signal_bar("AAA.SZ", 10.0),
                    _signal_bar("BBB.SZ", 10.0),
                ]
            ),
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )
    first_market = pd.DataFrame(
        [
            _execution_bar("AAA.SZ", 10.0, "20260709"),
            {
                **_execution_bar("BBB.SZ", 0.0, "20260709"),
                "is_suspended": True,
            },
        ]
    )

    first_resize = broker.resize_due_orders(
        synced.account_id,
        "20260709",
        first_market,
    )
    first_fill = broker.execute_due_orders(
        "20260709",
        first_market,
        [synced.account_id],
    )
    second_market = pd.DataFrame(
        [
            _execution_bar("AAA.SZ", 10.0, "20260710"),
            _execution_bar("BBB.SZ", 10.0, "20260710"),
        ]
    )
    second_resize = broker.resize_due_orders(
        synced.account_id,
        "20260710",
        second_market,
    )
    second_fill = broker.execute_due_orders(
        "20260710",
        second_market,
        [synced.account_id],
    )
    positions = broker.store.list_positions(synced.account_id)
    batch = broker.store.conn.execute(
        "SELECT status FROM paper_target_batch WHERE account_id = ?",
        [synced.account_id],
    ).fetchone()
    broker.close()

    assert first_resize.status == "PARTIAL"
    assert first_resize.created_orders == 1
    assert first_fill == (1, 0)
    assert second_resize.status == "RESIZED"
    assert second_resize.created_orders == 1
    assert second_fill == (1, 0)
    assert str(batch["status"]) == "APPLIED"
    assert sorted(item["quantity"] for item in positions) == [5_000, 5_000]


def test_legacy_account_does_not_resize_due_orders(tmp_path: Path) -> None:
    """未声明新政策的历史账户必须继续使用原收盘定量语义。"""
    broker = LocalPaperBroker(tmp_path / "paper.sqlite3")
    synced = broker.sync_target(
        PaperBrokerTarget(
            strategy_id="legacy_sizing_test",
            strategy_name="旧订单政策测试",
            trade_date="20260708",
            target_weights={"AAA.SZ": 0.5},
            market_data=pd.DataFrame([_signal_bar("AAA.SZ", 10.0)]),
            trading_dates=["20260708", "20260709"],
            initial_cash=100_000.0,
        )
    )

    resize = broker.resize_due_orders(
        synced.account_id,
        "20260709",
        pd.DataFrame([_execution_bar("AAA.SZ", 10.5)]),
    )
    orders = broker.store.list_orders(synced.account_id)
    broker.close()

    assert resize.status == "SKIPPED"
    assert orders[0]["status"] == "PENDING"
    assert orders[0]["quantity"] == 5_000


def _signal_bar(
    symbol: str,
    close_price: float,
    trade_date: str = "20260708",
) -> dict[str, object]:
    """构造盘后目标同步使用的信号日行情。"""
    return {
        **_execution_bar(symbol, close_price, trade_date),
        "close": close_price,
    }


def _execution_bar(
    symbol: str,
    open_price: float,
    trade_date: str = "20260709",
) -> dict[str, object]:
    """构造具备充足流动性的统一开盘行情。"""
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "name": symbol,
        "open": open_price,
        "close": open_price,
        "volume": 1_000_000,
        "is_suspended": False,
        "limit_up": False,
        "limit_down": False,
    }
