"""盘前风险确认应用服务。

风险任务由监控数据库实时生成，确认结果写入系统状态库。Markdown/CSV 仅用于展示，
不会作为下一次交易计算的事实来源。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import sqlite3
from typing import Any

from data.calendar import TradingCalendar
from runtime.live_risk_guard import build_risk_actions
from runtime.operations_ack import RESOLVED_STATUS, list_operations_ack, record_operations_ack
from runtime.paths import RuntimePaths


RISK_CONFIRMATION_SOURCE = "pre_market_check"
RISK_CONFIRMATION_CATEGORY = "risk_confirmation"
PROCEED_DECISION = "PROCEED"
PAUSE_DECISION = "PAUSE"
REDUCE_DECISION = "REDUCE"
ALLOWED_DECISIONS = {PROCEED_DECISION, PAUSE_DECISION, REDUCE_DECISION}


def build_risk_confirmation_state(
    paths: RuntimePaths,
    trade_date: str | None = None,
    previous_trade_date: str | None = None,
) -> dict[str, Any]:
    """构建指定交易日的盘前确认状态。"""
    target_date = _target_trade_date(trade_date)
    previous_date = previous_trade_date or _latest_market_date_before(paths, target_date)
    actions = build_risk_actions(paths, previous_date) if previous_date else []
    actionable_strategy_ids = _actionable_strategy_ids(paths)
    if actionable_strategy_ids is not None and hasattr(actions, "loc"):
        actions = actions.loc[actions["strategy_id"].isin(actionable_strategy_ids)].copy()
    acknowledgements = _acknowledgements_by_strategy(paths, target_date)
    tasks: list[dict[str, Any]] = []
    for action in actions.to_dict("records") if hasattr(actions, "to_dict") else actions:
        strategy_id = str(action["strategy_id"])
        acknowledgement = acknowledgements.get(strategy_id)
        decision = str(acknowledgement.get("decision") or "") if acknowledgement else ""
        tasks.append(
            {
                "trade_date": target_date,
                "previous_trade_date": previous_date,
                "strategy_id": strategy_id,
                "strategy_name": str(action["strategy_name"]),
                "severity": str(action["severity"]),
                "status": _task_status(decision),
                "decision": decision,
                "current_exposure": float(action["exposure"]),
                "recommended_max_exposure": float(action["recommended_max_exposure"]),
                "recommended_target_exposure": float(action["recommended_target_exposure"]),
                "daily_return": float(action["daily_return"]),
                "drawdown": float(action["drawdown"]),
                "volatility_20": float(action["volatility_20"]),
                "tradability_check": "确认停牌、跌停和集合竞价后，选择风险减仓、原计划撮合或暂停",
                "suggested_action": str(action["suggested_action"]),
                "reasons": str(action["reasons"]),
            }
        )
    return {
        "trade_date": target_date,
        "previous_trade_date": previous_date,
        "status": _overall_status(tasks),
        "task_count": len(tasks),
        "pending_count": sum(task["status"] == "PENDING_MANUAL_CONFIRM" for task in tasks),
        "tasks": tasks,
    }


def record_risk_confirmation(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    decision: str,
    resolution: str = "",
    operator: str = "local_user",
) -> dict[str, Any]:
    """记录风险减仓、允许撮合或暂停决定，并返回更新后的风险状态。"""
    normalized_decision = str(decision).strip().upper()
    if normalized_decision not in ALLOWED_DECISIONS:
        raise ValueError("decision must be REDUCE, PROCEED or PAUSE")
    state = build_risk_confirmation_state(paths, trade_date)
    task = next((item for item in state["tasks"] if item["strategy_id"] == strategy_id), None)
    if task is None:
        raise ValueError(f"没有待确认的策略风险任务: {strategy_id} {trade_date}")
    default_resolution = {
        REDUCE_DECISION: f"执行风险减仓至{float(task['recommended_target_exposure']):.0%}",
        PROCEED_DECISION: "允许按原策略计划进行Paper撮合",
        PAUSE_DECISION: "暂停当日Paper撮合",
    }[normalized_decision]
    record_operations_ack(
        paths.system_state_path,
        {
            "ack_id": f"risk-confirmation:{state['trade_date']}:{strategy_id}",
            "trade_date": state["trade_date"],
            "source": RISK_CONFIRMATION_SOURCE,
            "category": RISK_CONFIRMATION_CATEGORY,
            "name": strategy_id,
            "severity": task["severity"],
            "decision": normalized_decision,
            "message": task["reasons"],
            "resolution": resolution or default_resolution,
            "operator": operator,
            "status": RESOLVED_STATUS,
        },
    )
    return build_risk_confirmation_state(paths, state["trade_date"], state["previous_trade_date"])


def blocked_strategy_ids(state: dict[str, Any]) -> set[str]:
    """返回尚未明确允许撮合的策略集合。"""
    return {
        str(task["strategy_id"])
        for task in state.get("tasks", [])
        if str(task.get("decision") or "") not in {PROCEED_DECISION, REDUCE_DECISION}
    }


def risk_reduction_targets(state: dict[str, Any]) -> dict[str, float]:
    """返回已确认执行风险减仓的策略及目标总仓位。"""
    return {
        str(task["strategy_id"]): float(task["recommended_target_exposure"])
        for task in state.get("tasks", [])
        if str(task.get("decision") or "") == REDUCE_DECISION
    }


def _acknowledgements_by_strategy(paths: RuntimePaths, trade_date: str) -> dict[str, dict[str, Any]]:
    records = list_operations_ack(paths.system_state_path, limit=500)
    return {
        str(item["name"]): item
        for item in records
        if str(item.get("trade_date") or "") == trade_date
        and str(item.get("source") or "") == RISK_CONFIRMATION_SOURCE
        and str(item.get("category") or "") == RISK_CONFIRMATION_CATEGORY
    }


def _target_trade_date(value: str | None) -> str:
    compact = _compact_date(value or datetime.now().strftime("%Y%m%d"))
    calendar = TradingCalendar()
    if calendar.is_trading_day(compact):
        return compact
    next_day = calendar.next_trading_day(compact)
    return next_day.strftime("%Y%m%d") if next_day is not None else compact


def _latest_market_date_before(paths: RuntimePaths, trade_date: str) -> str:
    """优先使用监控事实中的上一交易日，避免周一误读周日。"""
    if paths.monitoring_path.exists():
        with sqlite3.connect(paths.monitoring_path) as con:
            table = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_nav_daily'"
            ).fetchone()
            if table is not None:
                row = con.execute(
                    "SELECT MAX(trade_date) FROM strategy_nav_daily WHERE trade_date < ?",
                    [trade_date],
                ).fetchone()
                if row and row[0]:
                    return _compact_date(str(row[0]))
    calendar = TradingCalendar()
    candidate = datetime.strptime(trade_date, "%Y%m%d")
    for offset in range(1, 15):
        previous = candidate - timedelta(days=offset)
        if calendar.is_trading_day(previous):
            return previous.strftime("%Y%m%d")
    return ""


def _actionable_strategy_ids(paths: RuntimePaths) -> set[str] | None:
    """只要求 Paper/Shadow Live 策略确认，纯研究观察策略不进入交易门禁。"""
    if not paths.system_state_path.exists():
        return None
    with sqlite3.connect(paths.system_state_path) as con:
        table = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_instances'"
        ).fetchone()
        if table is None:
            return None
        total = int(con.execute("SELECT COUNT(*) FROM strategy_instances").fetchone()[0])
        if total == 0:
            return None
        rows = con.execute(
            """
            SELECT strategy_id FROM strategy_instances
            WHERE enabled = 1 AND status IN ('paper', 'shadow_live')
            """
        ).fetchall()
    return {str(row[0]) for row in rows}


def _task_status(decision: str) -> str:
    if decision == REDUCE_DECISION:
        return "CONFIRMED_REDUCE"
    if decision == PROCEED_DECISION:
        return "CONFIRMED_PROCEED"
    if decision == PAUSE_DECISION:
        return "CONFIRMED_PAUSE"
    return "PENDING_MANUAL_CONFIRM"


def _overall_status(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "NO_ACTION"
    if any(task["status"] == "PENDING_MANUAL_CONFIRM" for task in tasks):
        return "NEED_CONFIRM"
    if any(task["status"] == "CONFIRMED_PAUSE" for task in tasks):
        return "PAUSED"
    if any(task["status"] == "CONFIRMED_REDUCE" for task in tasks):
        return "REDUCTION_READY"
    return "READY"


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text
