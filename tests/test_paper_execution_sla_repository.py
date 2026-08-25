"""Paper执行SLA账本与连续进度测试。"""

from __future__ import annotations

from pathlib import Path

from data.calendar import TradingCalendar
from runtime.market_open_paper_execution import MARKET_OPEN_EXECUTION_ID
from runtime.paper_execution_sla_repository import PaperExecutionSlaRepository
from runtime.paper_execution_sla_tracker import backfill_paper_execution_sla
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_progress_requires_strictly_consecutive_trading_days(tmp_path: Path) -> None:
    """失败日应清零，最新连续成功只能从失败后的下一交易日开始。"""
    repository = PaperExecutionSlaRepository(tmp_path / "system.sqlite")
    calendar = TradingCalendar(
        ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"]
    )
    for trade_date, status in [
        ("20260720", "SUCCESS"),
        ("20260721", "FAILED"),
        ("20260722", "SUCCESS"),
        ("20260723", "SUCCESS"),
        ("20260724", "SUCCESS"),
    ]:
        repository.record(_payload(trade_date, status))

    progress = repository.progress(required_days=20, calendar=calendar)

    assert progress["gate_status"] == "OBSERVING"
    assert progress["current_streak"] == 3
    assert progress["remaining_days"] == 17
    assert progress["longest_streak"] == 3
    assert progress["success_days"] == 4
    assert progress["failed_days"] == 1
    assert progress["pass_rate"] == 0.8


def test_missing_trading_day_breaks_current_streak(tmp_path: Path) -> None:
    """缺少稳定性任务证据不能被当作成功日跳过。"""
    repository = PaperExecutionSlaRepository(tmp_path / "system.sqlite")
    calendar = TradingCalendar(["2026-07-22", "2026-07-23", "2026-07-24"])
    repository.record(_payload("20260722", "SUCCESS"))
    repository.record(_payload("20260724", "SUCCESS"))

    progress = repository.progress(calendar=calendar)

    assert progress["current_streak"] == 1
    assert progress["missing_days"] == 1


def test_backfill_replays_existing_run_evidence_without_fabrication(tmp_path: Path) -> None:
    """历史回填只读取已有开盘任务记录，缺运行的日期必须记为失败。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.record_strategy_run(
        MARKET_OPEN_EXECUTION_ID,
        "20260723",
        "NO_ACTION",
        paths.runs_dir / "20260723",
        "ok",
    )
    calendar = TradingCalendar(["2026-07-23", "2026-07-24"])

    result = backfill_paper_execution_sla(
        paths,
        "20260723",
        "20260724",
        calendar,
    )
    history = PaperExecutionSlaRepository(paths.system_state_path).history()

    assert result["recorded_days"] == 2
    assert result["progress"]["current_streak"] == 0
    assert [item["status"] for item in history] == ["FAILED", "SUCCESS"]
    assert history[0]["issues"] == ["market_open_paper_execution 未运行"]


def _payload(trade_date: str, status: str) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "status": status,
        "run_status": "SUCCESS" if status == "SUCCESS" else "",
        "due_orders": 0,
        "filled_orders": 0,
        "rejected_orders": 0,
        "cancelled_orders": 0,
        "pending_orders": 0,
        "late_orders": 0,
        "issues": [] if status == "SUCCESS" else ["test failure"],
    }
