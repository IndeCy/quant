"""Paper目标权重持久化与T+1开盘订单重建。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import sqlite3
from typing import Any

import pandas as pd

from backtest.paper_execution import BrokerConfig
from backtest.paper_trading import PaperTradingStore
from runtime.paper_execution_policy import PaperExecutionPolicyManager


@dataclass(frozen=True)
class OpenOrderResizeResult:
    """一次开盘订单重建结果。"""

    status: str
    cancelled_orders: int = 0
    created_orders: int = 0
    reason: str = ""


class PaperOpenOrderSizingService:
    """把盘后目标权重延迟到T+1真实开盘价再转换成股数。"""

    def __init__(
        self,
        store: PaperTradingStore,
        policies: PaperExecutionPolicyManager,
    ) -> None:
        self.store = store
        self.policies = policies

    def save_target(
        self,
        account_id: int,
        signal_date: str,
        execute_date: str,
        target_weights: dict[str, float],
    ) -> bool:
        """仅为显式启用的账户保存完整目标组合。"""
        config = self.policies.load(account_id)
        if config is None or not config.open_aware_order_sizing:
            return False
        payload = json.dumps(
            {
                str(symbol): float(weight)
                for symbol, weight in sorted(target_weights.items())
                if float(weight) > 0
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self.store.conn:
            self.store.conn.execute(
                """
                UPDATE paper_target_batch
                SET status = 'SUPERSEDED', modify_time = CURRENT_TIMESTAMP
                WHERE account_id = ? AND status IN ('PENDING', 'PARTIAL')
                """,
                (account_id,),
            )
            self.store.conn.execute(
                """
                INSERT INTO paper_target_batch (
                  account_id, signal_date, execute_date, target_weights, status
                )
                VALUES (?, ?, ?, ?, 'PENDING')
                ON CONFLICT(account_id, execute_date) DO UPDATE SET
                  signal_date = excluded.signal_date,
                  target_weights = excluded.target_weights,
                  status = 'PENDING',
                  modify_time = CURRENT_TIMESTAMP
                """,
                (account_id, signal_date, execute_date, payload),
            )
        return True

    def resize_due_orders(
        self,
        account_id: int,
        trade_date: str,
        market: pd.DataFrame,
    ) -> OpenOrderResizeResult:
        """按开盘可执行价格原子替换当日策略委托。"""
        config = self.policies.load(account_id)
        if config is None or not config.open_aware_order_sizing:
            return OpenOrderResizeResult("SKIPPED", reason="POLICY_DISABLED")
        batch = self.store.conn.execute(
            """
            SELECT * FROM paper_target_batch
            WHERE account_id = ? AND execute_date <= ?
              AND status IN ('PENDING', 'PARTIAL')
            ORDER BY id DESC LIMIT 1
            """,
            (account_id, trade_date),
        ).fetchone()
        if batch is None:
            return OpenOrderResizeResult("SKIPPED", reason="TARGET_BATCH_MISSING")
        target_weights = {
            str(symbol): float(weight)
            for symbol, weight in json.loads(
                str(batch["target_weights"] or "{}")
            ).items()
        }
        positions = {
            str(item["symbol"]): item
            for item in self.store.list_positions(account_id)
        }
        symbols = sorted(
            set(target_weights)
            if str(batch["status"]) == "PARTIAL"
            else set(target_weights) | set(positions)
        )
        market_rows = _market_rows(market, trade_date)
        unavailable = [
            symbol
            for symbol in symbols
            if symbol not in market_rows
            or _open_price(market_rows[symbol]) <= 0
        ]
        account = self.store.get_account(account_id)
        total_value = float(account["cash"]) + sum(
            int(position["quantity"])
            * _valuation_price(market_rows.get(symbol), position)
            for symbol, position in positions.items()
        )
        target_quantities = _target_quantities(
            {
                symbol: weight
                for symbol, weight in target_weights.items()
                if symbol not in unavailable
            },
            market_rows,
            total_value,
            config,
        )
        # 缺价股票保持当前数量，避免单票停牌拖死整个组合。
        for symbol in unavailable:
            target_quantities[symbol] = int(
                positions.get(symbol, {}).get("quantity", 0)
            )
        deltas = {
            symbol: target_quantities.get(symbol, 0)
            - int(positions.get(symbol, {}).get("quantity", 0))
            for symbol in symbols
        }
        sell_deltas = {
            symbol: -quantity
            for symbol, quantity in deltas.items()
            if quantity < 0
        }
        buy_deltas = {
            symbol: quantity
            for symbol, quantity in deltas.items()
            if quantity > 0
        }
        available_cash = float(account["cash"]) + _estimated_sell_proceeds(
            sell_deltas,
            market_rows,
            config,
        )
        buy_deltas = _fit_buys_to_cash(
            buy_deltas,
            market_rows,
            available_cash,
            config,
        )
        result = self._replace_orders(
            account_id,
            trade_date,
            str(batch["signal_date"]),
            market_rows,
            sell_deltas,
            buy_deltas,
            int(batch["id"]),
            complete=not unavailable,
            unresolved_weights={
                symbol: float(target_weights.get(symbol, 0.0))
                for symbol in unavailable
            },
        )
        if not unavailable:
            return result
        return OpenOrderResizeResult(
            "PARTIAL",
            result.cancelled_orders,
            result.created_orders,
            "MISSING_OPEN_PRICE:" + "|".join(unavailable),
        )

    def _replace_orders(
        self,
        account_id: int,
        trade_date: str,
        signal_date: str,
        market_rows: dict[str, pd.Series],
        sell_deltas: dict[str, int],
        buy_deltas: dict[str, int],
        batch_id: int,
        *,
        complete: bool,
        unresolved_weights: dict[str, float],
    ) -> OpenOrderResizeResult:
        """在一个事务中取消旧单并写入开盘重建订单。"""
        original_rows = self.store.conn.execute(
            """
            SELECT * FROM paper_order
            WHERE account_id = ? AND status = 'PENDING' AND order_date <= ?
              AND note LIKE 'local_paper_broker%'
            """,
            (account_id, trade_date),
        ).fetchall()
        original = {str(row["symbol"]): dict(row) for row in original_rows}
        with self.store.conn:
            cursor = self.store.conn.execute(
                """
                UPDATE paper_order
                SET status = 'CANCELLED',
                    reject_reason = 'OPEN_AWARE_REPLAN',
                    modify_time = CURRENT_TIMESTAMP
                WHERE account_id = ? AND status = 'PENDING'
                  AND order_date <= ?
                  AND note LIKE 'local_paper_broker%'
                """,
                (account_id, trade_date),
            )
            created = 0
            for side, deltas in (("SELL", sell_deltas), ("BUY", buy_deltas)):
                for symbol, quantity in sorted(deltas.items()):
                    if quantity <= 0:
                        continue
                    row = original.get(symbol, {})
                    market_row = market_rows[symbol]
                    price = float(row.get("price") or _open_price(market_row))
                    name = str(
                        row.get("symbol_name")
                        or market_row.get("name")
                        or symbol
                    )
                    self.store.conn.execute(
                        """
                        INSERT INTO paper_order (
                          account_id, order_date, symbol, symbol_name, side,
                          price, quantity, amount, status, note
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                        """,
                        (
                            account_id,
                            trade_date,
                            symbol,
                            name,
                            side,
                            price,
                            int(quantity),
                            price * int(quantity),
                            f"local_paper_broker open_aware signal={signal_date}",
                        ),
                    )
                    created += 1
            if complete:
                self.store.conn.execute(
                    """
                    UPDATE paper_target_batch
                    SET status = 'APPLIED', modify_time = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (batch_id,),
                )
            else:
                self.store.conn.execute(
                    """
                    UPDATE paper_target_batch
                    SET status = 'PARTIAL', target_weights = ?,
                        modify_time = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        json.dumps(
                            unresolved_weights,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        batch_id,
                    ),
                )
        return OpenOrderResizeResult(
            "RESIZED",
            max(int(cursor.rowcount), 0),
            created,
        )


def ensure_paper_order_runtime_columns(connection: sqlite3.Connection) -> None:
    """兼容历史Paper库中执行结果扩展字段。"""
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(paper_order)").fetchall()
    }
    if "filled_quantity" not in columns:
        connection.execute(
            "ALTER TABLE paper_order ADD COLUMN filled_quantity integer "
            "NOT NULL DEFAULT 0"
        )
    if "reject_reason" not in columns:
        connection.execute(
            "ALTER TABLE paper_order ADD COLUMN reject_reason varchar(80) "
            "NOT NULL DEFAULT ''"
        )
    connection.commit()


def _market_rows(
    market: pd.DataFrame,
    trade_date: str,
) -> dict[str, pd.Series]:
    rows = market[market["trade_date"] == trade_date]
    return {
        str(row["symbol"]): row
        for _, row in rows.iterrows()
    }


def _target_quantities(
    weights: dict[str, float],
    market_rows: dict[str, pd.Series],
    total_value: float,
    config: BrokerConfig,
) -> dict[str, int]:
    result: dict[str, int] = {}
    lot_size = max(int(config.lot_size), 1)
    for symbol, weight in weights.items():
        expected_price = _open_price(market_rows[symbol]) * (
            1 + config.slippage_bps / 10_000
        )
        quantity = math.floor(
            total_value * float(weight) / expected_price / lot_size
        ) * lot_size
        if quantity > 0:
            result[symbol] = quantity
    return result


def _fit_buys_to_cash(
    quantities: dict[str, int],
    market_rows: dict[str, pd.Series],
    cash: float,
    config: BrokerConfig,
) -> dict[str, int]:
    current = dict(quantities)
    lot_size = max(int(config.lot_size), 1)
    for _ in range(4):
        cost = _estimated_buy_cost(current, market_rows, config)
        if cost <= cash + 1e-9:
            return current
        scale = max(min(cash / cost, 1.0), 0.0)
        current = {
            symbol: math.floor(quantity * scale / lot_size) * lot_size
            for symbol, quantity in current.items()
        }
        current = {
            symbol: quantity
            for symbol, quantity in current.items()
            if quantity > 0
        }
    return current


def _estimated_buy_cost(
    quantities: dict[str, int],
    market_rows: dict[str, pd.Series],
    config: BrokerConfig,
) -> float:
    return sum(
        _trade_cash(
            symbol,
            quantity,
            market_rows[symbol],
            "BUY",
            config,
        )
        for symbol, quantity in quantities.items()
    )


def _estimated_sell_proceeds(
    quantities: dict[str, int],
    market_rows: dict[str, pd.Series],
    config: BrokerConfig,
) -> float:
    return sum(
        _trade_cash(
            symbol,
            quantity,
            market_rows[symbol],
            "SELL",
            config,
        )
        for symbol, quantity in quantities.items()
    )


def _trade_cash(
    symbol: str,
    quantity: int,
    market_row: pd.Series,
    side: str,
    config: BrokerConfig,
) -> float:
    direction = 1 if side == "BUY" else -1
    fill_price = _open_price(market_row) * (
        1 + direction * config.slippage_bps / 10_000
    )
    notional = fill_price * quantity
    commission = max(
        notional * config.commission_rate,
        config.min_commission,
    )
    stamp_tax = (
        notional * config.stamp_tax_rate
        if side == "SELL" and symbol not in config.tax_exempt_symbols
        else 0.0
    )
    return (
        notional + commission
        if side == "BUY"
        else notional - commission - stamp_tax
    )


def _open_price(row: pd.Series) -> float:
    value = float(row.get("open", 0.0) or 0.0)
    return value if math.isfinite(value) and value > 0 else 0.0


def _valuation_price(
    row: pd.Series | None,
    position: dict[str, Any],
) -> float:
    """停牌或缺开盘价时用收盘价、成本价依次完成组合估值。"""
    if row is not None:
        for column in ("open", "close"):
            value = float(row.get(column, 0.0) or 0.0)
            if math.isfinite(value) and value > 0:
                return value
    return max(float(position.get("avg_cost", 0.0) or 0.0), 0.0)
