"""
测试模拟盘跟踪模块
"""

from pathlib import Path

from backtest.paper_trading import PaperTradingStore


def test_create_account_and_record_pending_orders(tmp_path: Path):
    """创建模拟账户后，应能记录收盘后提交但尚未成交的委托单。"""
    store = PaperTradingStore(tmp_path / "paper.sqlite3")
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1000000,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-06-05",
        )
        store.record_pending_order(
            account_id=account_id,
            order_date="2026-06-04",
            symbol="601138.SH",
            symbol_name="工业富联",
            side="BUY",
            price=78.56,
            quantity=3300,
            note="收盘后提交，等待成交",
        )

        orders = store.list_orders(account_id)

        assert len(orders) == 1
        assert orders[0]["status"] == "PENDING"
        assert orders[0]["amount"] == 259248.0
    finally:
        store.close()


def test_fill_pending_order_updates_position_and_cash(tmp_path: Path):
    """委托成交后，应扣减现金并增加对应持仓。"""
    store = PaperTradingStore(tmp_path / "paper.sqlite3")
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1000000,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-06-05",
        )
        order_id = store.record_pending_order(
            account_id=account_id,
            order_date="2026-06-04",
            symbol="000063.SZ",
            symbol_name="中兴通讯",
            side="BUY",
            price=37.75,
            quantity=6600,
        )

        store.fill_order(order_id=order_id, fill_date="2026-06-05", fill_price=37.75)

        positions = store.list_positions(account_id)
        account = store.get_account(account_id)
        orders = store.list_orders(account_id)
        assert positions[0]["symbol"] == "000063.SZ"
        assert positions[0]["quantity"] == 6600
        assert positions[0]["cost_amount"] == 249150.0
        assert account["cash"] == 750850.0
        assert orders[0]["status"] == "FILLED"
    finally:
        store.close()


def test_record_daily_snapshot_with_pending_and_position_state(tmp_path: Path):
    """每日快照应能同时保存账户净值、基线收益和调仓建议。"""
    store = PaperTradingStore(tmp_path / "paper.sqlite3")
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1000000,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-06-05",
        )

        store.record_daily_snapshot(
            account_id=account_id,
            trade_date="2026-06-05",
            total_value=1000000,
            cash=1000000,
            position_value=0,
            strategy_return=0,
            benchmark_return=0.01,
            excess_return=-0.01,
            strongest_chain="通信AI",
            rebalance_signal="BUY",
            target_symbols=["000063.SZ", "300308.SZ"],
        )

        snapshots = store.list_daily_snapshots(account_id)
        assert snapshots[0]["strongest_chain"] == "通信AI"
        assert snapshots[0]["target_symbols"] == ["000063.SZ", "300308.SZ"]
    finally:
        store.close()
