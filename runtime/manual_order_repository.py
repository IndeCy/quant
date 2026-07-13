"""人工调仓单仓库方法。"""

from __future__ import annotations

import uuid
from typing import Any

from runtime.manual_order import (
    ORDER_CONFIRMED_STATUS,
    ORDER_DRAFT_STATUS,
    ORDER_FILLED_STATUS,
    ORDER_REJECTED_STATUS,
    build_order_draft_from_snapshot,
    validate_batch_transition,
)


class ManualOrderRepositoryMixin:
    """保存手工调仓单、成交回填和审计日志。"""

    def create_manual_order_batch(self, snapshot: dict[str, Any], source: str = "account_snapshot") -> dict[str, Any]:
        """从账户快照幂等生成一批手工调仓订单。"""
        draft = build_order_draft_from_snapshot(snapshot)
        strategy_id = str(draft["strategy_id"])
        trade_date = str(draft["trade_date"])
        batch_id = _batch_id(strategy_id, trade_date)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO manual_order_batches(
                    batch_id, strategy_id, trade_date, status, source,
                    total_buy_amount, total_sell_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    status=excluded.status,
                    source=excluded.source,
                    total_buy_amount=excluded.total_buy_amount,
                    total_sell_amount=excluded.total_sell_amount,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    batch_id,
                    strategy_id,
                    trade_date,
                    ORDER_DRAFT_STATUS,
                    source,
                    float(draft["total_buy_amount"]),
                    float(draft["total_sell_amount"]),
                ],
            )
            con.execute("DELETE FROM manual_orders WHERE batch_id = ?", [batch_id])
            con.executemany(
                """
                INSERT INTO manual_orders(
                    order_id, batch_id, strategy_id, trade_date, symbol, side,
                    status, target_weight, actual_weight, drift_weight,
                    target_amount, actual_amount, trade_amount,
                    suggested_quantity, suggested_price, filled_quantity,
                    filled_price, reject_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_order_params(batch_id, item) for item in draft["orders"]],
            )
            _insert_audit(con, batch_id, "", "CREATE", f"created {len(draft['orders'])} manual orders")
        return self.load_manual_order_batch(strategy_id, trade_date) or draft

    def load_manual_order_batch(self, strategy_id: str, trade_date: str | None = None) -> dict[str, Any] | None:
        """读取某策略最近或指定日期的手工调仓批次。"""
        with self._connect() as con:
            if trade_date is None:
                batch = con.execute(
                    """
                    SELECT * FROM manual_order_batches
                    WHERE strategy_id = ?
                    ORDER BY trade_date DESC
                    LIMIT 1
                    """,
                    [strategy_id],
                ).fetchone()
            else:
                batch = con.execute(
                    "SELECT * FROM manual_order_batches WHERE strategy_id = ? AND trade_date = ?",
                    [strategy_id, trade_date],
                ).fetchone()
            if batch is None:
                return None
            result = self._row_to_dict(batch)
            orders = con.execute(
                """
                SELECT * FROM manual_orders
                WHERE batch_id = ?
                ORDER BY symbol
                """,
                [result["batch_id"]],
            ).fetchall()
            events = con.execute(
                """
                SELECT * FROM manual_order_audit_events
                WHERE batch_id = ?
                ORDER BY created_at, event_id
                """,
                [result["batch_id"]],
            ).fetchall()
        result["orders"] = [self._row_to_dict(row) for row in orders]
        result["audit_events"] = [self._row_to_dict(row) for row in events]
        return result

    def confirm_manual_order_batch(self, batch_id: str) -> dict[str, Any]:
        """确认一批手工调仓单，确认后才允许回填成交。"""
        batch = self._load_manual_order_batch_by_id(batch_id)
        validate_batch_transition(str(batch["status"]), ORDER_CONFIRMED_STATUS)
        with self._connect() as con:
            con.execute(
                "UPDATE manual_order_batches SET status = ?, modified_at = CURRENT_TIMESTAMP WHERE batch_id = ?",
                [ORDER_CONFIRMED_STATUS, batch_id],
            )
            con.execute(
                """
                UPDATE manual_orders
                SET status = ?, modified_at = CURRENT_TIMESTAMP
                WHERE batch_id = ? AND status = ?
                """,
                [ORDER_CONFIRMED_STATUS, batch_id, ORDER_DRAFT_STATUS],
            )
            _insert_audit(con, batch_id, "", "CONFIRM", "manual order batch confirmed")
        return self._load_manual_order_batch_by_id(batch_id)

    def fill_manual_order(self, order_id: str, filled_quantity: int, filled_price: float) -> dict[str, Any]:
        """回填单笔人工成交。"""
        order = self._load_manual_order_by_id(order_id)
        if str(order["status"]) != ORDER_CONFIRMED_STATUS:
            raise ValueError("only CONFIRMED manual order can be filled")
        with self._connect() as con:
            con.execute(
                """
                UPDATE manual_orders
                SET status = ?, filled_quantity = ?, filled_price = ?,
                    modified_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                """,
                [ORDER_FILLED_STATUS, int(filled_quantity), float(filled_price), order_id],
            )
            _insert_audit(con, str(order["batch_id"]), order_id, "FILL", f"filled {filled_quantity} @ {filled_price}")
        return self._load_manual_order_by_id(order_id)

    def reject_manual_order(self, order_id: str, reason: str) -> dict[str, Any]:
        """回填单笔人工拒绝/未成交。"""
        order = self._load_manual_order_by_id(order_id)
        if str(order["status"]) != ORDER_CONFIRMED_STATUS:
            raise ValueError("only CONFIRMED manual order can be rejected")
        with self._connect() as con:
            con.execute(
                """
                UPDATE manual_orders
                SET status = ?, reject_reason = ?, modified_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                """,
                [ORDER_REJECTED_STATUS, reason, order_id],
            )
            _insert_audit(con, str(order["batch_id"]), order_id, "REJECT", reason)
        return self._load_manual_order_by_id(order_id)

    def _load_manual_order_batch_by_id(self, batch_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM manual_order_batches WHERE batch_id = ?", [batch_id]).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return self.load_manual_order_batch(str(row["strategy_id"]), str(row["trade_date"])) or self._row_to_dict(row)

    def _load_manual_order_by_id(self, order_id: str) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM manual_orders WHERE order_id = ?", [order_id]).fetchone()
        if row is None:
            raise KeyError(order_id)
        return self._row_to_dict(row)


def _batch_id(strategy_id: str, trade_date: str) -> str:
    return f"{strategy_id}:{trade_date}"


def _order_params(batch_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    order_id = f"{batch_id}:{item['symbol']}"
    return (
        order_id,
        batch_id,
        str(item["strategy_id"]),
        str(item["trade_date"]),
        str(item["symbol"]),
        str(item["side"]),
        str(item["status"]),
        float(item["target_weight"]),
        float(item["actual_weight"]),
        float(item["drift_weight"]),
        float(item["target_amount"]),
        float(item["actual_amount"]),
        float(item["trade_amount"]),
        int(item["suggested_quantity"]),
        float(item["suggested_price"]),
        int(item["filled_quantity"]),
        float(item["filled_price"]),
        str(item["reject_reason"]),
    )


def _insert_audit(con: Any, batch_id: str, order_id: str, event_type: str, message: str) -> None:
    con.execute(
        """
        INSERT INTO manual_order_audit_events(
            event_id, batch_id, order_id, event_type, message
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [str(uuid.uuid4()), batch_id, order_id, event_type, message],
    )
