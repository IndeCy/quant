"""Paper Broker 的 T+1 执行服务等级审计。"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any

from data.calendar import TradingCalendar
from runtime.market_open_paper_execution import MARKET_OPEN_EXECUTION_ID
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


ACCEPTED_RUN_STATUSES = {"SUCCESS", "WARNING", "NO_ACTION"}


@dataclass(frozen=True)
class PaperExecutionSlaResult:
    """单个交易日的 Paper 执行完整性结果。"""

    trade_date: str
    status: str
    run_status: str
    due_orders: int
    filled_orders: int
    rejected_orders: int
    cancelled_orders: int
    pending_orders: int
    late_orders: int
    issues: tuple[str, ...]


def audit_paper_execution_sla(
    paths: RuntimePaths,
    trade_date: str,
    calendar: TradingCalendar | None = None,
) -> PaperExecutionSlaResult:
    """检查开盘任务是否运行，且到期订单是否在计划交易日内终结。"""
    target_date = _compact_date(trade_date)
    trading_calendar = calendar or TradingCalendar()
    if not trading_calendar.is_trading_day(target_date):
        return PaperExecutionSlaResult(
            target_date,
            "NOT_APPLICABLE",
            "",
            0,
            0,
            0,
            0,
            0,
            0,
            (),
        )

    run = SystemRepository(paths.system_state_path).get_run(MARKET_OPEN_EXECUTION_ID, target_date)
    run_status = str(run.get("status") or "") if run else ""
    counts = _order_counts(paths, target_date)
    issues: list[str] = []
    if not run:
        issues.append("market_open_paper_execution 未运行")
    elif run_status not in ACCEPTED_RUN_STATUSES:
        issues.append(f"market_open_paper_execution 状态异常: {run_status}")
    if counts["pending_orders"] > 0:
        issues.append(f"仍有 {counts['pending_orders']} 笔到期委托未处理")
    if counts["late_orders"] > 0:
        issues.append(f"发现 {counts['late_orders']} 笔跨交易日补成交/拒单")

    return PaperExecutionSlaResult(
        trade_date=target_date,
        status="FAILED" if issues else "SUCCESS",
        run_status=run_status,
        due_orders=counts["due_orders"],
        filled_orders=counts["filled_orders"],
        rejected_orders=counts["rejected_orders"],
        cancelled_orders=counts["cancelled_orders"],
        pending_orders=counts["pending_orders"],
        late_orders=counts["late_orders"],
        issues=tuple(issues),
    )


def _order_counts(paths: RuntimePaths, trade_date: str) -> dict[str, int]:
    """聚合同一计划成交日的终态，并识别此前到期却延至今日处理的订单。"""
    empty = {
        "due_orders": 0,
        "filled_orders": 0,
        "rejected_orders": 0,
        "cancelled_orders": 0,
        "pending_orders": 0,
        "late_orders": 0,
    }
    if not paths.paper_trading_path.exists():
        return empty
    iso_date = _iso_date(trade_date)
    with sqlite3.connect(paths.paper_trading_path) as con:
        row = con.execute(
            """
            SELECT
              COUNT(*) AS due_orders,
              SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) AS filled_orders,
              SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_orders,
              SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled_orders,
              SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) AS pending_orders
            FROM paper_order
            WHERE order_date = ?
            """,
            [iso_date],
        ).fetchone()
        late_row = con.execute(
            """
            SELECT COUNT(*) FROM paper_order
            WHERE order_date < ?
              AND fill_date = ?
              AND status IN ('FILLED', 'REJECTED')
            """,
            [iso_date, iso_date],
        ).fetchone()
    values = list(row or ())
    if len(values) != 5:
        return empty
    return {
        "due_orders": int(values[0] or 0),
        "filled_orders": int(values[1] or 0),
        "rejected_orders": int(values[2] or 0),
        "cancelled_orders": int(values[3] or 0),
        "pending_orders": int(values[4] or 0),
        "late_orders": int(late_row[0] or 0) if late_row else 0,
    }


def result_to_dict(result: PaperExecutionSlaResult) -> dict[str, Any]:
    """提供稳定序列化结构，供报告和后续 API 复用。"""
    return {
        "trade_date": result.trade_date,
        "status": result.status,
        "run_status": result.run_status,
        "due_orders": result.due_orders,
        "filled_orders": result.filled_orders,
        "rejected_orders": result.rejected_orders,
        "cancelled_orders": result.cancelled_orders,
        "pending_orders": result.pending_orders,
        "late_orders": result.late_orders,
        "issues": list(result.issues),
    }


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text


def _iso_date(value: str) -> str:
    text = _compact_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"
