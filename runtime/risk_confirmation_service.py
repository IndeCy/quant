"""盘前风险确认与撮合闭环应用服务。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time
from typing import Callable
from zoneinfo import ZoneInfo

from runtime.market_open_paper_execution import MarketOpenExecutionResult, run_market_open_paper_execution
from runtime.paths import RuntimePaths
from runtime.risk_confirmation import PAUSE_DECISION, record_risk_confirmation


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
EXECUTION_START = time(9, 35)
EXECUTION_END = time(15, 0)


def confirm_risk_action(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    decision: str,
    resolution: str = "",
    *,
    push: bool = False,
    now: datetime | None = None,
    execution_runner: Callable[..., MarketOpenExecutionResult] = run_market_open_paper_execution,
) -> dict[str, object]:
    """保存人工决定；若当天撮合时点已过，则立即复用统一撮合入口。"""
    state = record_risk_confirmation(paths, strategy_id, trade_date, decision, resolution)
    current = _shanghai_now(now)
    target_date = str(state["trade_date"])
    if str(decision).upper() == PAUSE_DECISION:
        state["execution"] = {"status": "PAUSED", "message": "今日撮合已暂停"}
        return state
    if target_date != current.strftime("%Y%m%d"):
        state["execution"] = {"status": "SCHEDULED", "message": "等待目标交易日开盘撮合"}
        return state
    if current.time() < EXECUTION_START:
        state["execution"] = {"status": "SCHEDULED", "message": "等待09:35开盘撮合"}
        return state
    if current.time() > EXECUTION_END:
        state["execution"] = {"status": "MISSED_WINDOW", "message": "已过当日撮合窗口，请在下一交易日重新确认"}
        return state

    result = execution_runner(paths=paths, trade_date=target_date, push=push)
    state["execution"] = {**asdict(result), "message": "风险决定已进入统一Paper撮合入口"}
    return state


def _shanghai_now(value: datetime | None) -> datetime:
    """统一使用上海时区判断人工确认是否需要立即执行。"""
    if value is None:
        return datetime.now(SHANGHAI_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(SHANGHAI_TZ)
