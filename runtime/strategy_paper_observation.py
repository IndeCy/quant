"""按策略记录长期Paper运行与T+1执行观察证据。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from data.calendar import TradingCalendar
from runtime.market_open_paper_execution import MARKET_OPEN_EXECUTION_ID
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.schema_version import apply_schema_migrations


ACCEPTED_EXECUTION_STATUSES = {"SUCCESS", "WARNING", "NO_ACTION"}


@dataclass(frozen=True)
class StrategyPaperObservation:
    """单策略单交易日的运行与撮合闭环结果。"""

    strategy_id: str
    trade_date: str
    status: str
    strategy_run_status: str
    execution_run_status: str
    due_orders: int
    filled_orders: int
    rejected_orders: int
    cancelled_orders: int
    pending_orders: int
    late_orders: int
    issues: tuple[str, ...]


def audit_strategy_paper_observation(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    calendar: TradingCalendar | None = None,
) -> StrategyPaperObservation:
    """按账户隔离审计，注册日不计入连续观察。"""
    target_date = _compact_date(trade_date)
    trading_calendar = calendar or TradingCalendar()
    if not trading_calendar.is_trading_day(target_date):
        return _empty_result(strategy_id, target_date, "NOT_APPLICABLE")
    account = _load_account(paths, strategy_id)
    if account is None:
        return _failed_without_account(strategy_id, target_date)
    if target_date <= _compact_date(str(account["start_date"])):
        return _empty_result(strategy_id, target_date, "NOT_APPLICABLE")

    repository = SystemRepository(paths.system_state_path)
    strategy_run = repository.get_run(strategy_id, target_date)
    execution_run = repository.get_run(MARKET_OPEN_EXECUTION_ID, target_date)
    strategy_status = str(strategy_run.get("status") or "") if strategy_run else ""
    execution_status = str(execution_run.get("status") or "") if execution_run else ""
    counts = _order_counts(paths, int(account["id"]), target_date)
    issues: list[str] = []
    if strategy_status != "SUCCESS":
        issues.append(f"策略运行状态异常: {strategy_status or '未运行'}")
    if execution_status not in ACCEPTED_EXECUTION_STATUSES:
        issues.append(f"开盘撮合状态异常: {execution_status or '未运行'}")
    if counts["pending_orders"]:
        issues.append(f"仍有{counts['pending_orders']}笔到期委托未处理")
    if counts["late_orders"]:
        issues.append(f"发现{counts['late_orders']}笔跨交易日处理")
    return StrategyPaperObservation(
        strategy_id,
        target_date,
        "FAILED" if issues else "SUCCESS",
        strategy_status,
        execution_status,
        counts["due_orders"],
        counts["filled_orders"],
        counts["rejected_orders"],
        counts["cancelled_orders"],
        counts["pending_orders"],
        counts["late_orders"],
        tuple(issues),
    )


class StrategyPaperObservationRepository:
    """保存按策略隔离的20交易日观察账本。"""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        apply_schema_migrations(self.path)

    def record(self, result: StrategyPaperObservation) -> None:
        """幂等记录审计事实。"""
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO strategy_paper_observation_daily (
                    strategy_id, trade_date, status, strategy_run_status,
                    execution_run_status, due_orders, filled_orders,
                    rejected_orders, cancelled_orders, pending_orders,
                    late_orders, issues_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id, trade_date) DO UPDATE SET
                    status=excluded.status,
                    strategy_run_status=excluded.strategy_run_status,
                    execution_run_status=excluded.execution_run_status,
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
                    result.strategy_id,
                    result.trade_date,
                    result.status,
                    result.strategy_run_status,
                    result.execution_run_status,
                    result.due_orders,
                    result.filled_orders,
                    result.rejected_orders,
                    result.cancelled_orders,
                    result.pending_orders,
                    result.late_orders,
                    json.dumps(list(result.issues), ensure_ascii=False),
                ],
            )

    def history(self, strategy_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """返回单策略最近观察记录。"""
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT * FROM strategy_paper_observation_daily
                WHERE strategy_id = ?
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                [strategy_id, max(int(limit), 1)],
            ).fetchall()
        return [_decode(row) for row in rows]

    def progress(
        self,
        strategy_id: str,
        required_days: int = 20,
        calendar: TradingCalendar | None = None,
    ) -> dict[str, Any]:
        """按真实交易日计算当前连续通过数。"""
        records = list(reversed(self.history(strategy_id, limit=2_000)))
        eligible = [item for item in records if item["status"] in {"SUCCESS", "FAILED"}]
        if not eligible:
            return _empty_progress(strategy_id, required_days)
        by_date = {str(item["trade_date"]): item for item in eligible}
        trading_calendar = calendar or TradingCalendar()
        expected = [
            day.strftime("%Y%m%d")
            for day in trading_calendar.trading_days(
                str(eligible[0]["trade_date"]),
                str(eligible[-1]["trade_date"]),
            )
        ]
        streak = 0
        for date in reversed(expected):
            if by_date.get(date, {}).get("status") != "SUCCESS":
                break
            streak += 1
        return {
            "strategy_id": strategy_id,
            "gate_status": "PASSED" if streak >= required_days else "OBSERVING",
            "required_days": required_days,
            "current_streak": streak,
            "remaining_days": max(required_days - streak, 0),
            "observed_days": len(eligible),
            "success_days": sum(item["status"] == "SUCCESS" for item in eligible),
            "failed_days": sum(item["status"] == "FAILED" for item in eligible),
            "latest_trade_date": str(eligible[-1]["trade_date"]),
            "latest_status": str(eligible[-1]["status"]),
            "latest_issues": list(eligible[-1]["issues"]),
        }


def record_strategy_paper_observation(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    required_days: int = 20,
) -> dict[str, Any]:
    """稳定性任务使用的审计、落库和进度聚合入口。"""
    result = audit_strategy_paper_observation(paths, strategy_id, trade_date)
    repository = StrategyPaperObservationRepository(paths.system_state_path)
    repository.record(result)
    return {
        "result": _result_dict(result),
        "progress": repository.progress(strategy_id, required_days),
    }


def _load_account(paths: RuntimePaths, strategy_id: str) -> sqlite3.Row | None:
    if not paths.paper_trading_path.exists():
        return None
    with sqlite3.connect(paths.paper_trading_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT id, start_date FROM paper_account WHERE strategy_code = ? ORDER BY id LIMIT 1",
            [strategy_id],
        ).fetchone()


def _order_counts(paths: RuntimePaths, account_id: int, trade_date: str) -> dict[str, int]:
    iso_date = _iso_date(trade_date)
    with sqlite3.connect(paths.paper_trading_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*),
              SUM(status='FILLED'), SUM(status='REJECTED'),
              SUM(status='CANCELLED'), SUM(status='PENDING')
            FROM paper_order WHERE account_id = ? AND order_date = ?
            """,
            [account_id, iso_date],
        ).fetchone()
        late = connection.execute(
            """
            SELECT COUNT(*) FROM paper_order
            WHERE account_id = ? AND order_date < ? AND fill_date = ?
              AND status IN ('FILLED', 'REJECTED')
            """,
            [account_id, iso_date, iso_date],
        ).fetchone()
    values = row or (0, 0, 0, 0, 0)
    return {
        "due_orders": int(values[0] or 0),
        "filled_orders": int(values[1] or 0),
        "rejected_orders": int(values[2] or 0),
        "cancelled_orders": int(values[3] or 0),
        "pending_orders": int(values[4] or 0),
        "late_orders": int(late[0] or 0) if late else 0,
    }


def _empty_result(strategy_id: str, trade_date: str, status: str) -> StrategyPaperObservation:
    return StrategyPaperObservation(strategy_id, trade_date, status, "", "", 0, 0, 0, 0, 0, 0, ())


def _failed_without_account(strategy_id: str, trade_date: str) -> StrategyPaperObservation:
    return StrategyPaperObservation(
        strategy_id, trade_date, "FAILED", "", "", 0, 0, 0, 0, 0, 0, ("Paper账户不存在",)
    )


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["issues"] = json.loads(str(result.pop("issues_json") or "[]"))
    return result


def _result_dict(result: StrategyPaperObservation) -> dict[str, Any]:
    return {**result.__dict__, "issues": list(result.issues)}


def _empty_progress(strategy_id: str, required_days: int) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "gate_status": "OBSERVING",
        "required_days": required_days,
        "current_streak": 0,
        "remaining_days": required_days,
        "observed_days": 0,
        "success_days": 0,
        "failed_days": 0,
        "latest_trade_date": "",
        "latest_status": "NO_DATA",
        "latest_issues": [],
    }


def _compact_date(value: str) -> str:
    return str(value).replace("-", "")[:8]


def _iso_date(value: str) -> str:
    text = _compact_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"
