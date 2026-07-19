"""运行异常人工确认日志。

用于记录用户已经看过哪些告警、采取了什么处置，不改变策略和调度行为。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Mapping
import uuid


ACK_STATUS = "ACKNOWLEDGED"
RESOLVED_STATUS = "RESOLVED"


def record_operations_ack(db_path: Path, payload: Mapping[str, object]) -> dict[str, object]:
    """记录一次人工确认动作。"""
    source = str(payload.get("source") or "").strip()
    category = str(payload.get("category") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not source or not category or not name:
        raise ValueError("source, category and name are required")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ack_id = str(payload.get("ack_id") or uuid.uuid4())
    params = {
        "ack_id": ack_id,
        "trade_date": str(payload.get("trade_date") or ""),
        "source": source,
        "category": category,
        "name": name,
        "severity": str(payload.get("severity") or "WARNING"),
        "decision": str(payload.get("decision") or ""),
        "message": str(payload.get("message") or ""),
        "resolution": str(payload.get("resolution") or ""),
        "operator": str(payload.get("operator") or "local_user"),
        "status": str(payload.get("status") or ACK_STATUS),
    }
    with _connect(db_path) as con:
        _ensure_schema(con)
        con.execute(
            """
            INSERT INTO operations_acknowledgements(
                ack_id, trade_date, source, category, name, severity, decision,
                message, resolution, operator, status
            ) VALUES (
                :ack_id, :trade_date, :source, :category, :name, :severity,
                :decision, :message, :resolution, :operator, :status
            )
            ON CONFLICT(ack_id) DO UPDATE SET
                severity=excluded.severity,
                decision=excluded.decision,
                message=excluded.message,
                resolution=excluded.resolution,
                operator=excluded.operator,
                status=excluded.status,
                modified_at=CURRENT_TIMESTAMP
            """,
            params,
        )
    return load_operations_ack(db_path, ack_id)


def list_operations_ack(db_path: Path, limit: int = 20) -> list[dict[str, object]]:
    """读取最近人工确认记录。"""
    if not db_path.exists():
        return []
    with _connect(db_path) as con:
        _ensure_schema(con)
        rows = con.execute(
            """
            SELECT * FROM operations_acknowledgements
            ORDER BY created_at DESC, ack_id DESC
            LIMIT ?
            """,
            [int(limit)],
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def load_operations_ack(db_path: Path, ack_id: str) -> dict[str, object]:
    """读取单条人工确认记录。"""
    with _connect(db_path) as con:
        _ensure_schema(con)
        row = con.execute("SELECT * FROM operations_acknowledgements WHERE ack_id = ?", [ack_id]).fetchone()
    if row is None:
        raise KeyError(ack_id)
    return _row_to_dict(row)


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS operations_acknowledgements (
            ack_id TEXT NOT NULL PRIMARY KEY,
            trade_date TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'WARNING',
            decision TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            resolution TEXT NOT NULL DEFAULT '',
            operator TEXT NOT NULL DEFAULT 'local_user',
            status TEXT NOT NULL DEFAULT 'ACKNOWLEDGED',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
