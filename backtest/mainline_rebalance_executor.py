"""
主线链动策略次日调仓执行器。

职责：
- 读取前一交易日盘后生成的明日预案
- 若次日尚未落模拟委托，则按开盘价自动补执行
- 成交时考虑滑点、流动性约束和成交失败
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Dict, List, Sequence

import pandas as pd

from backtest.cache import DEFAULT_CACHE_PATH, MarketDataCache
from backtest.paper_execution import BrokerConfig, BrokerSimulator, OrderManager, PaperOrder
from backtest.paper_trading import DEFAULT_PAPER_TRADING_PATH, PaperTradingStore
from examples.compare_chain_stock_selection import (
    ADJUST as STOCK_ADJUST,
    FREQUENCY as STOCK_FREQUENCY,
    TENCENT_PROVIDER as STOCK_PROVIDER,
    build_default_chain_definitions,
    fetch_tencent_stock_klines,
)


LOT_SIZE = 100


@dataclass(frozen=True)
class RebalanceExecutionResult:
    """次日调仓执行结果。"""

    trade_date: date
    signal_date: date | None
    executed: bool
    reason: str
    created_orders: int
    filled_orders: int
    partial_filled_orders: int
    rejected_orders: int
    target_symbols: List[str]


def _round_down_lot(quantity: int) -> int:
    """A 股按 100 股一手向下取整。"""
    return max(quantity // LOT_SIZE, 0) * LOT_SIZE


def _ensure_execution_columns(conn: sqlite3.Connection) -> None:
    """为订单表补齐执行明细字段，兼容老库。"""
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(paper_order)").fetchall()
    }
    if "filled_quantity" not in columns:
        conn.execute("ALTER TABLE paper_order ADD COLUMN filled_quantity integer NOT NULL DEFAULT 0")
    if "reject_reason" not in columns:
        conn.execute("ALTER TABLE paper_order ADD COLUMN reject_reason varchar(50) NOT NULL DEFAULT ''")
    conn.commit()


def _load_signal_snapshot(conn: sqlite3.Connection, account_id: int, trade_date: date) -> tuple[date | None, List[str], str]:
    """读取执行日之前最近一次盘后快照。"""
    row = conn.execute(
        """
        SELECT trade_date, rebalance_signal, target_symbols
        FROM paper_daily_snapshot
        WHERE account_id = ? AND trade_date < ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (account_id, trade_date.isoformat()),
    ).fetchone()
    if row is None:
        return None, [], "NO_PREVIOUS_SNAPSHOT"
    signal_date = date.fromisoformat(str(row["trade_date"]))
    target_symbols = json.loads(row["target_symbols"] or "[]")
    return signal_date, target_symbols, str(row["rebalance_signal"])


def _has_trade_date_orders(conn: sqlite3.Connection, account_id: int, trade_date: date) -> bool:
    """判断执行日是否已经有委托，避免重复补单。"""
    row = conn.execute(
        """
        SELECT 1
        FROM paper_order
        WHERE account_id = ? AND order_date = ?
        LIMIT 1
        """,
        (account_id, trade_date.isoformat()),
    ).fetchone()
    return row is not None


def _build_symbol_name_map() -> Dict[str, str]:
    """构建股票代码到名称的映射。"""
    name_map: Dict[str, str] = {}
    for chain in build_default_chain_definitions():
        for stock in chain.stocks:
            name_map[stock.symbol] = stock.name
    return name_map


def _load_market_bars(
    symbols: Sequence[str],
    trade_date: date,
    cache_path: Path | str,
) -> Dict[str, pd.DataFrame]:
    """读取执行日使用的不复权行情，优先刷新失败再回退缓存。"""
    bars_by_symbol: Dict[str, pd.DataFrame] = {}
    cache = MarketDataCache(cache_path)
    try:
        for symbol in symbols:
            try:
                bars_by_symbol[symbol] = fetch_tencent_stock_klines(
                    symbol=symbol,
                    fetch_start=trade_date,
                    fetch_end=trade_date,
                    adjust="none",
                    cache_path=cache_path,
                )
            except Exception:
                bars_by_symbol[symbol] = cache.read_bars(
                    provider=STOCK_PROVIDER,
                    symbol=symbol,
                    frequency=STOCK_FREQUENCY,
                    adjust="none",
                    start_date=trade_date,
                    end_date=trade_date,
                )
    finally:
        cache.close()
    return bars_by_symbol


def _get_trade_row(bars_by_symbol: Dict[str, pd.DataFrame], symbol: str, trade_date: date) -> pd.Series:
    """提取某只股票在执行日的行情行。"""
    bars = bars_by_symbol.get(symbol)
    if bars is None or bars.empty:
        raise ValueError(f"{symbol} 在 {trade_date.isoformat()} 无可用行情")
    sliced = bars[bars.index.date == trade_date]
    if sliced.empty:
        raise ValueError(f"{symbol} 在 {trade_date.isoformat()} 无可用行情")
    return sliced.iloc[-1]


def _calc_target_quantities(
    cash: float,
    positions: List[dict],
    target_symbols: Sequence[str],
    bars_by_symbol: Dict[str, pd.DataFrame],
    trade_date: date,
) -> Dict[str, int]:
    """按等权目标把总资产换算成次日开盘目标股数。"""
    total_capital = float(cash)
    for position in positions:
        row = _get_trade_row(bars_by_symbol, str(position["symbol"]), trade_date)
        total_capital += int(position["quantity"]) * float(row["open"])

    if not target_symbols:
        return {}
    target_value = total_capital / len(target_symbols)
    quantities: Dict[str, int] = {}
    for symbol in target_symbols:
        row = _get_trade_row(bars_by_symbol, symbol, trade_date)
        open_price = float(row["open"])
        if open_price <= 0:
            quantities[symbol] = 0
            continue
        quantities[symbol] = _round_down_lot(int(target_value / open_price))
    return quantities


def _create_execution_order(
    signal_date: date,
    trade_date: date,
    symbol: str,
    side: str,
    quantity: int,
    signal_price: float,
) -> PaperOrder:
    """构造单笔待执行委托对象。"""
    return PaperOrder(
        order_id=0,
        signal_date=signal_date.isoformat(),
        execute_date=trade_date.isoformat(),
        symbol=symbol,
        side=side,
        quantity=quantity,
        signal_price=signal_price,
    )


def _simulate_fill(
    broker: BrokerSimulator,
    order: PaperOrder,
    market_row: pd.Series,
    available_cash: float,
) -> tuple[str, int, float, str]:
    """在开盘价基础上模拟本笔委托的实际成交结果。"""
    temp_manager = OrderManager()
    temp_order = temp_manager.create_order(
        signal_date=order.signal_date,
        execute_date=order.execute_date,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        signal_price=order.signal_price,
    )
    filled = broker.execute(temp_order, market_row, temp_manager)
    if filled.status == "REJECTED":
        return "REJECTED", 0, 0.0, filled.reject_reason

    filled_quantity = _round_down_lot(int(filled.filled_quantity))
    if order.side == "BUY":
        affordable_quantity = _round_down_lot(int(available_cash / float(filled.fill_price)))
        filled_quantity = min(filled_quantity, affordable_quantity)
        if filled_quantity <= 0:
            return "REJECTED", 0, 0.0, "INSUFFICIENT_CASH_NO_FILL"
    if filled_quantity <= 0:
        return "REJECTED", 0, 0.0, "LIQUIDITY_NO_FILL"
    status = "FILLED" if filled_quantity >= order.quantity else "PARTIAL_FILLED"
    return status, filled_quantity, float(filled.fill_price), ""


def _apply_fill(conn: sqlite3.Connection, account_id: int, symbol: str, symbol_name: str, side: str, quantity: int, amount: float) -> None:
    """按成交结果更新现金和持仓。"""
    account = conn.execute("SELECT cash FROM paper_account WHERE id = ?", (account_id,)).fetchone()
    if account is None:
        raise ValueError(f"模拟账户不存在: {account_id}")
    position = conn.execute(
        "SELECT quantity, cost_amount FROM paper_position WHERE account_id = ? AND symbol = ?",
        (account_id, symbol),
    ).fetchone()

    if side == "BUY":
        if float(account["cash"]) + 1e-6 < amount:
            raise ValueError("账户现金不足，无法成交买入委托")
        old_quantity = int(position["quantity"]) if position else 0
        old_cost = float(position["cost_amount"]) if position else 0.0
        new_quantity = old_quantity + quantity
        new_cost = old_cost + amount
        avg_cost = new_cost / new_quantity if new_quantity else 0.0
        conn.execute("UPDATE paper_account SET cash = cash - ?, modify_time = CURRENT_TIMESTAMP WHERE id = ?", (amount, account_id))
        conn.execute(
            """
            INSERT INTO paper_position (account_id, symbol, symbol_name, quantity, cost_amount, avg_cost)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, symbol)
            DO UPDATE SET
              quantity = excluded.quantity,
              cost_amount = excluded.cost_amount,
              avg_cost = excluded.avg_cost,
              modify_time = CURRENT_TIMESTAMP
            """,
            (account_id, symbol, symbol_name, new_quantity, new_cost, avg_cost),
        )
        return

    if position is None or int(position["quantity"]) < quantity:
        raise ValueError("持仓不足，无法成交卖出委托")
    old_quantity = int(position["quantity"])
    old_cost = float(position["cost_amount"])
    new_quantity = old_quantity - quantity
    new_cost = old_cost * new_quantity / old_quantity if new_quantity else 0.0
    conn.execute("UPDATE paper_account SET cash = cash + ?, modify_time = CURRENT_TIMESTAMP WHERE id = ?", (amount, account_id))
    if new_quantity == 0:
        conn.execute("DELETE FROM paper_position WHERE account_id = ? AND symbol = ?", (account_id, symbol))
    else:
        conn.execute(
            """
            UPDATE paper_position
            SET quantity = ?, cost_amount = ?, avg_cost = ?, modify_time = CURRENT_TIMESTAMP
            WHERE account_id = ? AND symbol = ?
            """,
            (new_quantity, new_cost, new_cost / new_quantity, account_id, symbol),
        )


def execute_due_rebalance(
    account_id: int,
    trade_date: date,
    db_path: Path | str = DEFAULT_PAPER_TRADING_PATH,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    broker_config: BrokerConfig | None = None,
    market_bars: Dict[str, pd.DataFrame] | None = None,
) -> RebalanceExecutionResult:
    """执行前一交易日已经生成、但尚未落单的明日预案。"""
    store = PaperTradingStore(db_path)
    try:
        conn = store.conn
        _ensure_execution_columns(conn)
        signal_date, target_symbols, signal = _load_signal_snapshot(conn, account_id, trade_date)
        if signal_date is None:
            return RebalanceExecutionResult(trade_date, None, False, "NO_PREVIOUS_SNAPSHOT", 0, 0, 0, 0, [])
        if signal != "SWITCH" or not target_symbols:
            return RebalanceExecutionResult(trade_date, signal_date, False, "NO_DUE_SWITCH_SIGNAL", 0, 0, 0, 0, target_symbols)
        if _has_trade_date_orders(conn, account_id, trade_date):
            return RebalanceExecutionResult(trade_date, signal_date, False, "ORDERS_ALREADY_EXIST", 0, 0, 0, 0, target_symbols)

        account = store.get_account(account_id)
        positions = store.list_positions(account_id)
        current_symbols = {str(position["symbol"]) for position in positions}
        if current_symbols == set(target_symbols):
            return RebalanceExecutionResult(trade_date, signal_date, False, "POSITIONS_ALREADY_MATCH", 0, 0, 0, 0, target_symbols)

        symbols = sorted(current_symbols | set(target_symbols))
        bars_by_symbol = market_bars or _load_market_bars(symbols, trade_date, cache_path)
        target_quantities = _calc_target_quantities(float(account["cash"]), positions, target_symbols, bars_by_symbol, trade_date)
        current_quantities = {str(position["symbol"]): int(position["quantity"]) for position in positions}
        name_map = _build_symbol_name_map()
        broker = BrokerSimulator(broker_config or BrokerConfig())

        created_orders = 0
        filled_orders = 0
        partial_filled_orders = 0
        rejected_orders = 0
        execution_plan: List[tuple[str, str, int]] = []
        for symbol in sorted(set(current_quantities) | set(target_quantities)):
            delta = target_quantities.get(symbol, 0) - current_quantities.get(symbol, 0)
            if delta < 0:
                execution_plan.append((symbol, "SELL", abs(delta)))
        for symbol in sorted(set(current_quantities) | set(target_quantities)):
            delta = target_quantities.get(symbol, 0) - current_quantities.get(symbol, 0)
            if delta > 0:
                execution_plan.append((symbol, "BUY", delta))

        for symbol, side, quantity in execution_plan:
            if quantity <= 0:
                continue
            row = _get_trade_row(bars_by_symbol, symbol, trade_date)
            signal_price = float(row["close"] if "close" in row else row["open"])
            order_id = store.record_pending_order(
                account_id=account_id,
                order_date=trade_date.isoformat(),
                symbol=symbol,
                symbol_name=name_map.get(symbol, symbol),
                side=side,
                price=float(row["open"]),
                quantity=quantity,
                note=f"补执行 {signal_date.isoformat()} 盘后明日预案",
            )
            created_orders += 1

            account_after_order = store.get_account(account_id)
            status, filled_quantity, fill_price, reject_reason = _simulate_fill(
                broker=broker,
                order=_create_execution_order(signal_date, trade_date, symbol, side, quantity, signal_price),
                market_row=row,
                available_cash=float(account_after_order["cash"]),
            )
            amount = fill_price * filled_quantity if filled_quantity > 0 else 0.0

            if status in {"FILLED", "PARTIAL_FILLED"} and filled_quantity > 0:
                _apply_fill(conn, account_id, symbol, name_map.get(symbol, symbol), side, filled_quantity, amount)
                conn.execute(
                    """
                    UPDATE paper_order
                    SET fill_date = ?, fill_price = ?, filled_quantity = ?, amount = ?, status = ?, reject_reason = '',
                        modify_time = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (trade_date.isoformat(), fill_price, filled_quantity, amount, status, order_id),
                )
                if status == "FILLED":
                    filled_orders += 1
                else:
                    partial_filled_orders += 1
            else:
                conn.execute(
                    """
                    UPDATE paper_order
                    SET fill_date = ?, fill_price = 0, filled_quantity = 0, amount = 0, status = 'REJECTED',
                        reject_reason = ?, modify_time = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (trade_date.isoformat(), reject_reason, order_id),
                )
                rejected_orders += 1
            conn.commit()

        return RebalanceExecutionResult(
            trade_date=trade_date,
            signal_date=signal_date,
            executed=created_orders > 0,
            reason="EXECUTED",
            created_orders=created_orders,
            filled_orders=filled_orders,
            partial_filled_orders=partial_filled_orders,
            rejected_orders=rejected_orders,
            target_symbols=list(target_symbols),
        )
    finally:
        store.close()
