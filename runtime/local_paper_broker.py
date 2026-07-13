"""统一本地 Paper Broker 适配层。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.paper_execution import BrokerConfig, BrokerSimulator, OrderManager, PaperOrder
from backtest.paper_trading import PaperTradingStore


LOT_SIZE = 100


@dataclass(frozen=True)
class PaperBrokerTarget:
    """策略盘后目标组合，统一进入本地模拟券商。"""

    strategy_id: str
    strategy_name: str
    trade_date: str
    target_weights: dict[str, float]
    market_data: pd.DataFrame
    trading_dates: list[str]
    initial_cash: float = 1_000_000.0
    benchmark_symbol: str = "510300"
    benchmark_name: str = "沪深300"


@dataclass(frozen=True)
class PaperBrokerSyncResult:
    """本地模拟券商同步结果。"""

    account_id: int
    trade_date: str
    next_trade_date: str
    created_orders: int
    executed_orders: int
    rejected_orders: int
    pending_orders: int


class LocalPaperBroker:
    """把策略目标权重转成统一模拟盘委托、成交和持仓。"""

    def __init__(self, db_path: str | Path, broker_config: BrokerConfig | None = None) -> None:
        self.store = PaperTradingStore(db_path)
        self.broker = BrokerSimulator(broker_config or BrokerConfig())
        self._ensure_execution_columns()

    def close(self) -> None:
        """关闭底层模拟盘数据库。"""
        self.store.close()

    def sync_target(self, target: PaperBrokerTarget) -> PaperBrokerSyncResult:
        """执行到期委托，并为最新目标组合创建 T+1 委托。"""
        trade_date = _compact_date(target.trade_date)
        trade_iso = _iso_date(trade_date)
        market = _normalize_market_data(target.market_data)
        dates = sorted(_compact_date(item) for item in target.trading_dates)
        next_trade_date = _next_trade_date(trade_date, dates)
        account_id = self._get_or_create_account(target, trade_iso)

        executed, rejected = self._execute_due_orders(account_id, trade_iso, market)
        created = 0
        if next_trade_date:
            created = self._create_next_orders(account_id, target, trade_date, _iso_date(next_trade_date), market)
        self._record_snapshot(account_id, target, trade_date, market)
        pending = len(self.store.list_orders(account_id, status="PENDING"))
        return PaperBrokerSyncResult(account_id, trade_date, next_trade_date or "", created, executed, rejected, pending)

    def execute_due_orders(self, trade_date: str, market_data: pd.DataFrame) -> tuple[int, int]:
        """撮合所有账户在指定交易日到期的待成交委托。"""
        market = _normalize_market_data(market_data)
        return self._execute_due_orders(None, _iso_date(trade_date), market)

    def _get_or_create_account(self, target: PaperBrokerTarget, start_date: str) -> int:
        row = self.store.conn.execute(
            "SELECT id FROM paper_account WHERE strategy_code = ? ORDER BY id LIMIT 1",
            (target.strategy_id,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        return self.store.create_account(
            strategy_name=target.strategy_name,
            strategy_code=target.strategy_id,
            initial_cash=target.initial_cash,
            benchmark_symbol=target.benchmark_symbol,
            benchmark_name=target.benchmark_name,
            start_date=start_date,
        )

    def _execute_due_orders(self, account_id: int | None, trade_iso: str, market: pd.DataFrame) -> tuple[int, int]:
        account_filter = "" if account_id is None else "account_id = ? AND"
        params: tuple[Any, ...] = (trade_iso,) if account_id is None else (account_id, trade_iso)
        rows = self.store.conn.execute(
            f"""
            SELECT * FROM paper_order
            WHERE {account_filter} status = 'PENDING' AND order_date <= ?
            ORDER BY id
            """,
            params,
        ).fetchall()
        executed = 0
        rejected = 0
        for row in rows:
            order = dict(row)
            market_row = _market_row(market, trade_iso, str(order["symbol"]))
            if market_row is None:
                self._mark_rejected(int(order["id"]), trade_iso, "MISSING_MARKET_DATA")
                rejected += 1
                continue
            manager = OrderManager()
            paper_order = manager.create_order(
                signal_date=str(order["note"]).split("signal=", 1)[-1] if "signal=" in str(order["note"]) else trade_iso,
                execute_date=trade_iso,
                symbol=str(order["symbol"]),
                side=str(order["side"]),
                quantity=int(order["quantity"]),
                signal_price=float(order["price"]),
            )
            filled = self.broker.execute(paper_order, market_row, manager)
            if filled.status == "REJECTED":
                self._mark_rejected(int(order["id"]), trade_iso, filled.reject_reason)
                rejected += 1
                continue
            quantity = _round_lot(int(filled.filled_quantity))
            if quantity <= 0:
                self._mark_rejected(int(order["id"]), trade_iso, "LOT_SIZE_NO_FILL")
                rejected += 1
                continue
            amount = quantity * float(filled.fill_price)
            self._apply_fill(int(order["account_id"]), str(order["symbol"]), str(order["symbol_name"]), str(order["side"]), quantity, amount)
            self.store.conn.execute(
                """
                UPDATE paper_order
                SET fill_date = ?, fill_price = ?, filled_quantity = ?, amount = ?, status = ?,
                    reject_reason = '', modify_time = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (trade_iso, float(filled.fill_price), quantity, amount, filled.status, int(order["id"])),
            )
            executed += 1
        self.store.conn.commit()
        return executed, rejected

    def _create_next_orders(
        self,
        account_id: int,
        target: PaperBrokerTarget,
        signal_date: str,
        execute_iso: str,
        market: pd.DataFrame,
    ) -> int:
        if self._has_orders(account_id, execute_iso):
            return 0
        target_quantities = self._target_quantities(account_id, target.target_weights, signal_date, market)
        current_quantities = {str(row["symbol"]): int(row["quantity"]) for row in self.store.list_positions(account_id)}
        created = 0
        for symbol in sorted(set(target_quantities) | set(current_quantities)):
            delta = target_quantities.get(symbol, 0) - current_quantities.get(symbol, 0)
            if delta == 0:
                continue
            price_row = _market_row(market, _iso_date(signal_date), symbol)
            if price_row is None:
                continue
            side = "BUY" if delta > 0 else "SELL"
            self.store.record_pending_order(
                account_id=account_id,
                order_date=execute_iso,
                symbol=symbol,
                symbol_name=str(price_row.get("name") or symbol),
                side=side,
                price=float(price_row["close"]),
                quantity=abs(int(delta)),
                note=f"local_paper_broker signal={_iso_date(signal_date)}",
            )
            created += 1
        return created

    def _target_quantities(
        self,
        account_id: int,
        target_weights: dict[str, float],
        signal_date: str,
        market: pd.DataFrame,
    ) -> dict[str, int]:
        prices = _prices_for_date(market, _iso_date(signal_date))
        total_value = self._account_total_value(account_id, prices)
        quantities: dict[str, int] = {}
        for symbol, weight in target_weights.items():
            price = prices.get(symbol)
            if price is None or price <= 0 or weight <= 0:
                continue
            quantities[symbol] = _round_lot(int(total_value * float(weight) / price))
        return quantities

    def _account_total_value(self, account_id: int, prices: dict[str, float]) -> float:
        account = self.store.get_account(account_id)
        total = float(account["cash"])
        for row in self.store.list_positions(account_id):
            total += int(row["quantity"]) * float(prices.get(str(row["symbol"]), row["avg_cost"]))
        return total

    def _record_snapshot(self, account_id: int, target: PaperBrokerTarget, trade_date: str, market: pd.DataFrame) -> None:
        prices = _prices_for_date(market, _iso_date(trade_date))
        account = self.store.get_account(account_id)
        position_value = sum(
            int(row["quantity"]) * float(prices.get(str(row["symbol"]), row["avg_cost"]))
            for row in self.store.list_positions(account_id)
        )
        total_value = float(account["cash"]) + position_value
        initial_cash = float(account["initial_cash"]) or 1.0
        self.store.record_daily_snapshot(
            account_id=account_id,
            trade_date=_iso_date(trade_date),
            total_value=total_value,
            cash=float(account["cash"]),
            position_value=position_value,
            strategy_return=total_value / initial_cash - 1.0,
            benchmark_return=0.0,
            excess_return=total_value / initial_cash - 1.0,
            strongest_chain="",
            rebalance_signal="TARGET_SYNC",
            target_symbols=sorted(target.target_weights),
        )

    def _apply_fill(self, account_id: int, symbol: str, name: str, side: str, quantity: int, amount: float) -> None:
        if side == "BUY":
            self.store._apply_buy(account_id, symbol, name, quantity, amount)  # noqa: SLF001 - 复用现有持仓入账逻辑。
        else:
            self.store._apply_sell(account_id, symbol, quantity, amount)  # noqa: SLF001 - 复用现有持仓出账逻辑。

    def _mark_rejected(self, order_id: int, trade_iso: str, reason: str) -> None:
        self.store.conn.execute(
            """
            UPDATE paper_order
            SET fill_date = ?, status = 'REJECTED', reject_reason = ?, modify_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (trade_iso, reason, order_id),
        )

    def _has_orders(self, account_id: int, execute_iso: str) -> bool:
        row = self.store.conn.execute(
            "SELECT 1 FROM paper_order WHERE account_id = ? AND order_date = ? LIMIT 1",
            (account_id, execute_iso),
        ).fetchone()
        return row is not None

    def _ensure_execution_columns(self) -> None:
        columns = {row["name"] for row in self.store.conn.execute("PRAGMA table_info(paper_order)").fetchall()}
        if "filled_quantity" not in columns:
            self.store.conn.execute("ALTER TABLE paper_order ADD COLUMN filled_quantity integer NOT NULL DEFAULT 0")
        if "reject_reason" not in columns:
            self.store.conn.execute("ALTER TABLE paper_order ADD COLUMN reject_reason varchar(80) NOT NULL DEFAULT ''")
        self.store.conn.commit()


def _normalize_market_data(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "trade_date" not in data.columns and "date" in data.columns:
        data["trade_date"] = data["date"]
    if "symbol" not in data.columns and "ts_code" in data.columns:
        data["symbol"] = data["ts_code"]
    if "volume" not in data.columns and "vol" in data.columns:
        data["volume"] = data["vol"]
    data["trade_date"] = data["trade_date"].map(lambda value: _iso_date(str(value)))
    for column in ["is_suspended", "limit_up", "limit_down"]:
        if column not in data.columns:
            data[column] = False
    return data.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _market_row(data: pd.DataFrame, trade_iso: str, symbol: str) -> pd.Series | None:
    rows = data[(data["trade_date"] == trade_iso) & (data["symbol"] == symbol)]
    return None if rows.empty else rows.iloc[-1]


def _prices_for_date(data: pd.DataFrame, trade_iso: str) -> dict[str, float]:
    rows = data[data["trade_date"] == trade_iso]
    return {str(row["symbol"]): float(row["close"]) for _, row in rows.iterrows() if math.isfinite(float(row["close"]))}


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text


def _iso_date(value: str) -> str:
    text = _compact_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _next_trade_date(trade_date: str, trading_dates: list[str]) -> str:
    for item in sorted(trading_dates):
        if item > trade_date:
            return item
    return ""


def _round_lot(quantity: int) -> int:
    return max(int(quantity) // LOT_SIZE, 0) * LOT_SIZE
