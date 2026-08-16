"""
Paper Trading 的 T+1 开盘目标重算回放器。

该模块仅在 ``open_aware_order_sizing`` 显式开启时使用，避免改变历史
Paper 默认语义。成交、费用和限制仍由原有 ``BrokerSimulator`` 处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from backtest.paper_execution import PaperOrder, PaperTradingResult

if TYPE_CHECKING:
    from backtest.paper_execution import PaperTradingEngine


@dataclass(frozen=True)
class _PendingTarget:
    """等待成交日按开盘行情落地的目标权重。"""

    signal_date: str
    execute_date: str
    weights: dict[str, float]
    signal_prices: dict[str, float]
    retry_symbols: frozenset[str] | None = None


def run_open_aware_replay(
    engine: "PaperTradingEngine",
    signals_by_date: dict[str, dict[str, float]],
    market_data: pd.DataFrame,
) -> PaperTradingResult:
    """按 T 日信号、T+1 开盘重算股数的口径执行历史回放。"""
    data = engine._normalize_market_data(market_data)
    trading_dates = sorted(data["date"].unique())
    market_by_date = {
        date: rows.set_index("symbol", drop=False)
        for date, rows in data.groupby("date", sort=False)
    }
    signals = {
        pd.Timestamp(date).strftime("%Y-%m-%d"): weights
        for date, weights in signals_by_date.items()
    }
    pending_targets: dict[str, list[_PendingTarget]] = {}
    latest_prices: dict[str, float] = {}
    snapshots = []
    for index, date in enumerate(trading_dates):
        daily_market = market_by_date[date]
        for target in pending_targets.pop(date, []):
            unresolved = _execute_target_at_open(
                engine,
                target,
                daily_market,
                latest_prices,
            )
            if unresolved and index + 1 < len(trading_dates):
                next_date = trading_dates[index + 1]
                pending_targets.setdefault(next_date, []).append(
                    _PendingTarget(
                        signal_date=target.signal_date,
                        execute_date=next_date,
                        weights=target.weights,
                        signal_prices=target.signal_prices,
                        retry_symbols=frozenset(unresolved),
                    )
                )
        latest_prices.update(_valid_prices(daily_market, "close"))
        if date in signals:
            execute_date = engine._execution_date(date, trading_dates)
            if execute_date is not None:
                # 新信号覆盖此前未完成目标，避免继续执行过期权重。
                pending_targets[execute_date] = [
                    _PendingTarget(
                        signal_date=date,
                        execute_date=execute_date,
                        weights=dict(signals[date]),
                        signal_prices=dict(latest_prices),
                    )
                ]
        snapshots.append(engine.portfolio.snapshot(date, latest_prices))
    actual_turnover = (
        engine.portfolio.traded_notional / engine.initial_cash
        if engine.initial_cash
        else 0.0
    )
    total_cost = engine.portfolio.total_fees + sum(
        log.execution_impact
        for log in engine.order_manager.execution_logs
        if log.status != "REJECTED"
    )
    return PaperTradingResult(
        orders=engine.order_manager.orders,
        executions=engine.order_manager.execution_logs,
        snapshots=snapshots,
        actual_turnover=actual_turnover,
        total_execution_cost=total_cost,
    )


def _execute_target_at_open(
    engine: "PaperTradingEngine",
    target: _PendingTarget,
    daily_market: pd.DataFrame,
    latest_prices: dict[str, float],
) -> set[str]:
    """用成交日开盘价和预期滑点重算整手目标，再进入统一撮合器。"""
    open_prices = _valid_prices(daily_market, "open")
    symbols = (
        set(target.retry_symbols)
        if target.retry_symbols is not None
        else set(target.weights) | set(engine.portfolio.actual_holdings)
    )
    unavailable = symbols - set(open_prices)
    valuation_prices = dict(latest_prices)
    valuation_prices.update(open_prices)
    portfolio_value = engine.portfolio.snapshot(
        target.execute_date,
        valuation_prices,
    ).total_value
    expected_fill_prices = {
        symbol: price * (1 + engine.broker.config.slippage_bps / 10_000)
        for symbol, price in open_prices.items()
    }
    scoped_weights = {
        symbol: float(target.weights.get(symbol, 0.0))
        for symbol in symbols
    }
    scoped_targets = engine._target_holdings(
        scoped_weights,
        expected_fill_prices,
        portfolio_value,
    )
    target_holdings = (
        dict(engine.portfolio.target_holdings)
        if target.retry_symbols is not None
        else {}
    )
    target_holdings.update(scoped_targets)
    # 单票缺价只冻结该票，后续仅重试尚未完成的股票。
    for symbol in unavailable:
        target_holdings[symbol] = engine.portfolio.actual_holdings.get(
            symbol,
            0,
        )
    engine.portfolio.set_target_holdings(target_holdings)
    orders = _create_scoped_orders(
        engine,
        target.signal_date,
        target.execute_date,
        target_holdings,
        target.signal_prices,
        symbols,
    )
    _execute_orders(engine, orders, daily_market)
    return unavailable


def _create_scoped_orders(
    engine: "PaperTradingEngine",
    signal_date: str,
    execute_date: str,
    target_holdings: dict[str, int],
    signal_prices: dict[str, float],
    symbols: set[str],
) -> list[PaperOrder]:
    """只为本批待完成股票创建订单，避免重试时重复调整正常持仓。"""
    orders: list[PaperOrder] = []
    for symbol in sorted(symbols):
        delta = (
            target_holdings.get(symbol, 0)
            - engine.portfolio.actual_holdings.get(symbol, 0)
        )
        signal_price = float(signal_prices.get(symbol, 0.0))
        if delta == 0 or signal_price <= 0:
            continue
        orders.append(
            engine.order_manager.create_order(
                signal_date,
                execute_date,
                symbol,
                "BUY" if delta > 0 else "SELL",
                abs(delta),
                signal_price,
            )
        )
    return orders


def _execute_orders(
    engine: "PaperTradingEngine",
    orders: list[PaperOrder],
    daily_market: pd.DataFrame,
) -> None:
    """卖单优先于买单，逐笔成交后刷新现金。"""
    for order in sorted(
        orders,
        key=lambda item: (item.side == "BUY", item.symbol),
    ):
        market_row = engine._market_row(daily_market, order.symbol)
        filled = engine.broker.execute(
            order,
            market_row,
            engine.order_manager,
            cash_available=engine.portfolio.cash,
        )
        if filled.status not in {"FILLED", "PARTIAL_FILLED"}:
            continue
        log = engine.order_manager.execution_logs[-1]
        engine.portfolio.apply_fill(
            filled.symbol,
            filled.side,
            filled.filled_quantity,
            filled.fill_price,
            filled.signal_price,
            commission=log.commission,
            stamp_tax=log.stamp_tax,
        )


def _valid_prices(
    daily_market: pd.DataFrame,
    column: str,
) -> dict[str, float]:
    """提取大于零的有效行情价格。"""
    return {
        str(row["symbol"]): float(row[column])
        for _, row in daily_market.iterrows()
        if pd.notna(row[column]) and float(row[column]) > 0
    }
