"""Paper T+1 SLA 日账本与连续通过进度。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from data.calendar import TradingCalendar
from runtime.schema_version import apply_schema_migrations


class PaperExecutionSlaRepository:
    """将每日审计事实保存到系统状态库，不从报告文件推断结果。"""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        apply_schema_migrations(self.path)

    def record(self, payload: dict[str, Any]) -> None:
        """按交易日幂等保存 SLA 审计结果。"""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_execution_sla_daily (
                    trade_date, status, run_status, due_orders, filled_orders,
                    rejected_orders, cancelled_orders, pending_orders,
                    late_orders, issues_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    status=excluded.status,
                    run_status=excluded.run_status,
                    due_orders=excluded.due_orders,
                    filled_orders=excluded.filled_orders,
                    rejected_orders=excluded.rejected_orders,
                    cancelled_orders=excluded.cancelled_orders,
                    pending_orders=excluded.pending_orders,
                    late_orders=excluded.late_orders,
                    issues_json=excluded.issues_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    str(payload["trade_date"]),
                    str(payload["status"]),
                    str(payload.get("run_status") or ""),
                    int(payload.get("due_orders") or 0),
                    int(payload.get("filled_orders") or 0),
                    int(payload.get("rejected_orders") or 0),
                    int(payload.get("cancelled_orders") or 0),
                    int(payload.get("pending_orders") or 0),
                    int(payload.get("late_orders") or 0),
                    json.dumps(
                        list(payload.get("issues") or []),
                        ensure_ascii=False,
                    ),
                ],
            )

    def history(self, limit: int = 60) -> list[dict[str, Any]]:
        """按日期倒序返回观察历史。"""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM paper_execution_sla_daily
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                [max(int(limit), 1)],
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def progress(
        self,
        required_days: int = 20,
        calendar: TradingCalendar | None = None,
    ) -> dict[str, Any]:
        """计算严格连续交易日通过数，缺记录也会中断连续性。"""
        if required_days < 1:
            raise ValueError("required_days 必须大于等于1")
        records = list(reversed(self.history(limit=2_000)))
        eligible = [
            item for item in records
            if item["status"] in {"SUCCESS", "FAILED"}
        ]
        if not eligible:
            return _empty_progress(required_days)

        trading_calendar = calendar or TradingCalendar()
        by_date = {str(item["trade_date"]): item for item in eligible}
        first_date = str(eligible[0]["trade_date"])
        latest_date = str(eligible[-1]["trade_date"])
        expected_dates = [
            day.strftime("%Y%m%d")
            for day in trading_calendar.trading_days(first_date, latest_date)
        ]
        current_streak = _current_success_streak(expected_dates, by_date)
        longest_streak = _longest_success_streak(expected_dates, by_date)
        success_count = sum(item["status"] == "SUCCESS" for item in eligible)
        failure_count = sum(item["status"] == "FAILED" for item in eligible)
        missing_count = sum(day not in by_date for day in expected_dates)
        latest = by_date.get(latest_date, eligible[-1])
        return {
            "gate_status": "PASSED" if current_streak >= required_days else "OBSERVING",
            "required_days": required_days,
            "current_streak": current_streak,
            "remaining_days": max(required_days - current_streak, 0),
            "longest_streak": longest_streak,
            "observed_days": len(eligible),
            "success_days": success_count,
            "failed_days": failure_count,
            "missing_days": missing_count,
            "pass_rate": success_count / len(eligible),
            "latest_trade_date": latest_date,
            "latest_status": str(latest["status"]),
            "latest_issues": list(latest["issues"]),
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["issues"] = json.loads(str(result.pop("issues_json") or "[]"))
    return result


def _current_success_streak(
    expected_dates: list[str],
    by_date: dict[str, dict[str, Any]],
) -> int:
    streak = 0
    for trade_date in reversed(expected_dates):
        record = by_date.get(trade_date)
        if record is None or record["status"] != "SUCCESS":
            break
        streak += 1
    return streak


def _longest_success_streak(
    expected_dates: list[str],
    by_date: dict[str, dict[str, Any]],
) -> int:
    longest = 0
    current = 0
    for trade_date in expected_dates:
        record = by_date.get(trade_date)
        current = current + 1 if record and record["status"] == "SUCCESS" else 0
        longest = max(longest, current)
    return longest


def _empty_progress(required_days: int) -> dict[str, Any]:
    return {
        "gate_status": "OBSERVING",
        "required_days": required_days,
        "current_streak": 0,
        "remaining_days": required_days,
        "longest_streak": 0,
        "observed_days": 0,
        "success_days": 0,
        "failed_days": 0,
        "missing_days": 0,
        "pass_rate": 0.0,
        "latest_trade_date": "",
        "latest_status": "NO_DATA",
        "latest_issues": [],
    }
