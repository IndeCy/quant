"""统一账户视图仓库方法。"""

from __future__ import annotations

from typing import Any


class PortfolioAccountRepositoryMixin:
    """保存策略账户快照和持仓差异。"""

    def upsert_account_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """幂等保存账户快照。"""
        strategy_id = str(snapshot["strategy_id"])
        trade_date = str(snapshot["trade_date"])
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO account_snapshots(
                    strategy_id, trade_date, total_value, cash, cash_weight,
                    position_value, target_position_weight, max_abs_drift
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id, trade_date) DO UPDATE SET
                    total_value=excluded.total_value,
                    cash=excluded.cash,
                    cash_weight=excluded.cash_weight,
                    position_value=excluded.position_value,
                    target_position_weight=excluded.target_position_weight,
                    max_abs_drift=excluded.max_abs_drift,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    strategy_id,
                    trade_date,
                    float(snapshot["total_value"]),
                    float(snapshot["cash"]),
                    float(snapshot["cash_weight"]),
                    float(snapshot["position_value"]),
                    float(snapshot["target_position_weight"]),
                    float(snapshot["max_abs_drift"]),
                ],
            )
            con.execute(
                "DELETE FROM account_positions WHERE strategy_id = ? AND trade_date = ?",
                [strategy_id, trade_date],
            )
            con.executemany(
                """
                INSERT INTO account_positions(
                    strategy_id, trade_date, symbol, target_weight, actual_weight,
                    drift_weight, target_amount, actual_amount, trade_amount,
                    action, quantity, last_close
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_position_params(strategy_id, trade_date, item) for item in snapshot.get("positions", [])],
            )
        return self.load_account_snapshot(strategy_id, trade_date) or snapshot

    def load_account_snapshot(self, strategy_id: str, trade_date: str | None = None) -> dict[str, Any] | None:
        """读取某策略账户快照，默认读取最近日期。"""
        with self._connect() as con:
            if trade_date is None:
                snapshot = con.execute(
                    """
                    SELECT * FROM account_snapshots
                    WHERE strategy_id = ?
                    ORDER BY trade_date DESC
                    LIMIT 1
                    """,
                    [strategy_id],
                ).fetchone()
            else:
                snapshot = con.execute(
                    "SELECT * FROM account_snapshots WHERE strategy_id = ? AND trade_date = ?",
                    [strategy_id, trade_date],
                ).fetchone()
            if snapshot is None:
                return None
            snapshot_dict = self._row_to_dict(snapshot)
            rows = con.execute(
                """
                SELECT * FROM account_positions
                WHERE strategy_id = ? AND trade_date = ?
                ORDER BY symbol
                """,
                [strategy_id, snapshot_dict["trade_date"]],
            ).fetchall()
        snapshot_dict["positions"] = [self._row_to_dict(row) for row in rows]
        return snapshot_dict


def _position_params(strategy_id: str, trade_date: str, item: dict[str, Any]) -> tuple[Any, ...]:
    """把持仓差异转成 SQLite 参数。"""
    return (
        strategy_id,
        trade_date,
        str(item["symbol"]),
        float(item.get("target_weight", 0.0)),
        float(item.get("actual_weight", 0.0)),
        float(item.get("drift_weight", 0.0)),
        float(item.get("target_amount", 0.0)),
        float(item.get("actual_amount", 0.0)),
        float(item.get("trade_amount", 0.0)),
        str(item.get("action", "HOLD")),
        int(item.get("quantity", 0) or 0),
        float(item.get("last_close", 0.0) or 0.0),
    )
