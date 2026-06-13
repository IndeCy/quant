"""
测试主线链动策略盘后观察模块
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.chain_selection import ChainDefinition, ChainStock
from backtest.mainline_observer import MarketSnapshot, observe_account
from backtest.paper_trading import PaperTradingStore


def make_bars(start: str, periods: int, first_close: float, step: float) -> pd.DataFrame:
    """构造满足动量窗口要求的最小日线数据。"""
    dates = pd.date_range(start=start, periods=periods, freq="B")
    closes = [first_close + step * index for index in range(periods)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1000000] * periods,
            "amount": [0.0] * periods,
        },
        index=dates,
    )


def make_late_jump_bars(
    start: str,
    periods: int,
    base_close: float,
    early_step: float,
    final_jump: float,
) -> pd.DataFrame:
    """构造前期平稳、最后一天明显转强的测试日线。"""
    dates = pd.date_range(start=start, periods=periods, freq="B")
    closes = [base_close + early_step * index for index in range(periods - 1)]
    closes.append(closes[-1] + final_jump)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1000000] * periods,
            "amount": [0.0] * periods,
        },
        index=dates,
    )


def build_test_chains() -> list[ChainDefinition]:
    """构造更小的测试产业链定义，避免依赖真实股票池。"""
    return [
        ChainDefinition(
            name="通信AI",
            proxy_symbol="CHAIN_A",
            stocks=[
                ChainStock("A1", "通信一号", "通信AI", "设备"),
                ChainStock("A2", "通信二号", "通信AI", "光模块"),
            ],
        ),
        ChainDefinition(
            name="半导体",
            proxy_symbol="CHAIN_B",
            stocks=[
                ChainStock("B1", "半导体一号", "半导体", "设备"),
                ChainStock("B2", "半导体二号", "半导体", "设计"),
            ],
        ),
    ]


def seed_account(db_path: Path) -> int:
    """创建带两只持仓的模拟盘账户。"""
    store = PaperTradingStore(db_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=100000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-01-01",
        )
        order_a = store.record_pending_order(account_id, "2026-01-01", "A1", "通信一号", "BUY", 10.0, 1000)
        order_b = store.record_pending_order(account_id, "2026-01-01", "A2", "通信二号", "BUY", 20.0, 1000)
        store.fill_order(order_a, "2026-01-02", 10.0)
        store.fill_order(order_b, "2026-01-02", 20.0)
        return account_id
    finally:
        store.close()


def test_observe_account_falls_back_to_cached_trade_date_and_no_rebalance(tmp_path: Path):
    """请求日没有新行情时，应沿用缓存最新收盘且不生成明日预案。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = seed_account(db_path)
    chains = build_test_chains()

    bars_a = make_bars("2026-01-01", 122, 10.0, 0.10)
    bars_b = make_bars("2026-01-01", 122, 20.0, 0.08)
    weak_bars = make_bars("2026-01-01", 122, 30.0, 0.02)
    benchmark = make_bars("2026-01-01", 122, 3000.0, 1.0)

    def loader(symbols, fetch_start, fetch_end, cache_path):
        assert "A1" in symbols
        return MarketSnapshot(
            trade_date=date(2026, 6, 5),
            stock_bars={
                "A1": bars_a,
                "A2": bars_b,
                "B1": weak_bars,
                "B2": weak_bars,
                "CHAIN_A": make_bars("2026-01-01", 122, 100.0, 0.5),
                "CHAIN_B": make_bars("2026-01-01", 122, 100.0, 0.1),
            },
            benchmark_bars=benchmark,
            refresh_notes=["mock fallback"],
        )

    result = observe_account(
        account_id=account_id,
        requested_date="2026-06-08",
        db_path=db_path,
        market_loader=loader,
        chains=chains,
    )

    assert result.trade_date == date(2026, 6, 5)
    assert result.strongest_chain == "通信AI"
    assert result.rebalance_signal == "NONE"
    assert "当前使用本地缓存截至 2026-06-05" in result.summary_text
    assert "B策略: 今日未产生明日调仓信号" in result.summary_text


def test_observe_account_builds_tomorrow_plan_when_b_signal_switches(tmp_path: Path):
    """当 B 策略在调仓日切到新强链时，应输出明日预案。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = seed_account(db_path)
    chains = build_test_chains()

    old_chain_stock = make_bars("2026-01-01", 121, 10.0, 0.12)
    old_chain_stock_2 = make_bars("2026-01-01", 121, 20.0, 0.10)
    new_chain_stock = make_late_jump_bars("2026-01-01", 121, 15.0, 0.02, 18.0)
    new_chain_stock_2 = make_late_jump_bars("2026-01-01", 121, 18.0, 0.02, 16.0)
    benchmark = make_bars("2026-01-01", 121, 3000.0, 1.0)
    trade_date = old_chain_stock.index[-1].date()

    def loader(symbols, fetch_start, fetch_end, cache_path):
        return MarketSnapshot(
            trade_date=trade_date,
            stock_bars={
                "A1": old_chain_stock,
                "A2": old_chain_stock_2,
                "B1": new_chain_stock,
                "B2": new_chain_stock_2,
                "CHAIN_A": make_bars("2026-01-01", 121, 100.0, 0.12),
                "CHAIN_B": make_late_jump_bars("2026-01-01", 121, 100.0, 0.03, 22.0),
            },
            benchmark_bars=benchmark,
            refresh_notes=[],
        )

    result = observe_account(
        account_id=account_id,
        requested_date=trade_date.isoformat(),
        db_path=db_path,
        market_loader=loader,
        chains=chains,
    )

    assert result.strongest_chain == "半导体"
    assert result.rebalance_signal == "SWITCH"
    assert result.target_symbols == ["B1", "B2"]
    assert "明日预案:" in result.summary_text
    assert "B1, B2" in result.summary_text


def test_observe_account_uses_actual_return_base_for_mainline_account(tmp_path: Path):
    """主线链动真实观察应按券商软件的 100 万本金口径计算收益率。"""
    db_path = tmp_path / "paper.sqlite3"
    store = PaperTradingStore(db_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1001437.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-01-01",
        )
        order_id = store.record_pending_order(account_id, "2026-01-01", "A1", "通信一号", "BUY", 100.1437, 10000)
        store.fill_order(order_id, "2026-01-02", 100.1437)
    finally:
        store.close()

    bars = make_bars("2026-01-01", 122, 97.6685, 0.0)
    benchmark = make_bars("2026-01-01", 122, 3000.0, 1.0)
    chains = [
        ChainDefinition(
            name="通信AI",
            proxy_symbol="CHAIN_A",
            stocks=[ChainStock("A1", "通信一号", "通信AI", "设备")],
        )
    ]

    def loader(symbols, fetch_start, fetch_end, cache_path):
        return MarketSnapshot(
            trade_date=date(2026, 6, 9),
            stock_bars={
                "A1": bars,
                "CHAIN_A": make_bars("2026-01-01", 122, 100.0, 0.2),
            },
            benchmark_bars=benchmark,
            refresh_notes=[],
        )

    result = observe_account(
        account_id=account_id,
        requested_date="2026-06-09",
        db_path=db_path,
        market_loader=loader,
        chains=chains,
    )

    assert round(result.total_value, 2) == 976685.0
    assert round(result.strategy_return * 100, 2) == -2.33
    assert "总收益率 -2.33%" in result.summary_text


def test_observe_account_values_positions_with_unadjusted_prices(tmp_path: Path):
    """真实持仓估值应优先使用不复权价格，避免和券商市值口径偏离。"""
    db_path = tmp_path / "paper.sqlite3"
    store = PaperTradingStore(db_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1001437.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-01-01",
        )
        order_id = store.record_pending_order(account_id, "2026-01-01", "A1", "通信一号", "BUY", 100.0, 1000)
        store.fill_order(order_id, "2026-01-02", 100.0)
    finally:
        store.close()

    qfq_bars = make_bars("2026-01-01", 122, 80.0, 0.0)
    raw_bars = make_bars("2026-01-01", 122, 95.0, 0.0)
    benchmark = make_bars("2026-01-01", 122, 3000.0, 1.0)
    chains = [
        ChainDefinition(
            name="通信AI",
            proxy_symbol="CHAIN_A",
            stocks=[ChainStock("A1", "通信一号", "通信AI", "设备")],
        )
    ]

    def loader(symbols, fetch_start, fetch_end, cache_path):
        return MarketSnapshot(
            trade_date=date(2026, 6, 9),
            stock_bars={
                "A1": qfq_bars,
                "CHAIN_A": make_bars("2026-01-01", 122, 100.0, 0.2),
            },
            benchmark_bars=benchmark,
            refresh_notes=[],
            valuation_bars={
                "A1": raw_bars,
                "CHAIN_A": make_bars("2026-01-01", 122, 100.0, 0.2),
            },
        )

    result = observe_account(
        account_id=account_id,
        requested_date="2026-06-09",
        db_path=db_path,
        market_loader=loader,
        chains=chains,
    )

    assert round(result.positions[0].close_price, 2) == 95.0
    assert round(result.position_value, 2) == 95000.0
    assert round(result.total_value, 2) == 996437.0


def test_observe_account_includes_cash_dividend_in_position_pnl(tmp_path: Path):
    """单票盈亏应把已入账分红现金计入，和券商持仓盈亏口径保持一致。"""
    db_path = tmp_path / "paper.sqlite3"
    store = PaperTradingStore(db_path)
    try:
        account_id = store.create_account(
            strategy_name="主线链动策略",
            strategy_code="Mainline_Chain_Momentum",
            initial_cash=1000000.0,
            benchmark_symbol="000001.SH",
            benchmark_name="上证指数",
            start_date="2026-01-01",
        )
        order_id = store.record_pending_order(account_id, "2026-01-01", "A1", "通信一号", "BUY", 100.0, 300)
        store.fill_order(order_id, "2026-01-02", 100.0)
        store.apply_corporate_action(
            account_id=account_id,
            symbol="A1",
            ex_date="2026-06-11",
            action_type="DIVIDEND_BONUS",
            quantity_delta=120,
            cash_delta=270.0,
            note="10派10元转4股",
        )
    finally:
        store.close()

    qfq_bars = make_bars("2026-01-01", 122, 80.0, 0.0)
    raw_bars = make_bars("2026-01-01", 122, 95.0, 0.0)
    benchmark = make_bars("2026-01-01", 122, 3000.0, 1.0)
    chains = [
        ChainDefinition(
            name="通信AI",
            proxy_symbol="CHAIN_A",
            stocks=[ChainStock("A1", "通信一号", "通信AI", "设备")],
        )
    ]

    def loader(symbols, fetch_start, fetch_end, cache_path):
        return MarketSnapshot(
            trade_date=date(2026, 6, 11),
            stock_bars={
                "A1": qfq_bars,
                "CHAIN_A": make_bars("2026-01-01", 122, 100.0, 0.2),
            },
            benchmark_bars=benchmark,
            refresh_notes=[],
            valuation_bars={
                "A1": raw_bars,
                "CHAIN_A": make_bars("2026-01-01", 122, 100.0, 0.2),
            },
        )

    result = observe_account(
        account_id=account_id,
        requested_date="2026-06-11",
        db_path=db_path,
        market_loader=loader,
        chains=chains,
    )

    assert result.positions[0].quantity == 420
    assert round(result.positions[0].market_value, 2) == 39900.0
    assert round(result.positions[0].pnl_amount, 2) == 10170.0
    assert round(result.positions[0].pnl_ratio * 100, 2) == 33.9
