"""Paper T+1 SLA 审计、持久化与历史回填入口。"""

from __future__ import annotations

from dataclasses import dataclass

from data.calendar import TradingCalendar
from runtime.paper_execution_sla import (
    PaperExecutionSlaResult,
    audit_paper_execution_sla,
    result_to_dict,
)
from runtime.paper_execution_sla_repository import PaperExecutionSlaRepository
from runtime.paths import RuntimePaths


@dataclass(frozen=True)
class PaperExecutionSlaTracking:
    """一次审计及其写入后的连续观察进度。"""

    result: PaperExecutionSlaResult
    progress: dict[str, object]


def record_daily_paper_execution_sla(
    paths: RuntimePaths,
    trade_date: str,
    calendar: TradingCalendar | None = None,
) -> PaperExecutionSlaTracking:
    """审计并幂等记录一个日期，稳定性任务与人工回放共用。"""
    result = audit_paper_execution_sla(paths, trade_date, calendar)
    repository = PaperExecutionSlaRepository(paths.system_state_path)
    repository.record(result_to_dict(result))
    return PaperExecutionSlaTracking(
        result=result,
        progress=repository.progress(calendar=calendar),
    )


def backfill_paper_execution_sla(
    paths: RuntimePaths,
    start_date: str,
    end_date: str,
    calendar: TradingCalendar | None = None,
) -> dict[str, object]:
    """仅依据已有运行与订单事实回放历史交易日，不修改原始记录。"""
    trading_calendar = calendar or TradingCalendar()
    repository = PaperExecutionSlaRepository(paths.system_state_path)
    recorded = 0
    for day in trading_calendar.trading_days(start_date, end_date):
        result = audit_paper_execution_sla(
            paths,
            day.strftime("%Y%m%d"),
            trading_calendar,
        )
        repository.record(result_to_dict(result))
        recorded += 1
    return {
        "start_date": str(start_date).replace("-", ""),
        "end_date": str(end_date).replace("-", ""),
        "recorded_days": recorded,
        "progress": repository.progress(calendar=trading_calendar),
    }
