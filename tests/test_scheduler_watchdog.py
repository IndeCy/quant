"""调度稳定性巡检测试。"""

from pathlib import Path

import pandas as pd
import pytest

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.scheduler_watchdog import run_scheduler_watchdog
from runtime.strategy_commit_journal import StrategyCommitJournalRepository
from runtime.strategy_instance_catalog import register_builtin_strategy_instances


def test_scheduler_watchdog_does_not_notify_when_all_jobs_succeeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """全部调度产物正常时，只写巡检记录，不发送 Bark。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_success_state(paths, "20260702")
    notifications: list[str] = []

    monkeypatch.setattr("runtime.scheduler_watchdog._today", lambda: "20260702")
    monkeypatch.setattr(
        "runtime.scheduler_watchdog.send_bark_notification",
        lambda title, body: notifications.append(body),
    )

    result = run_scheduler_watchdog(paths, push=True)
    run = SystemRepository(paths.system_state_path).get_run("scheduler_watchdog", "20260702")

    assert result.status == "SUCCESS"
    assert result.issue_count == 0
    assert notifications == []
    assert run is not None
    assert run["status"] == "SUCCESS"


def test_scheduler_watchdog_notifies_when_trading_pipeline_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """交易流水线缺失时必须发异常 Bark。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    register_builtin_strategy_instances(SystemRepository(paths.system_state_path))
    notifications: list[dict[str, str]] = []

    monkeypatch.setattr("runtime.scheduler_watchdog._today", lambda: "20260702")

    def capture(title: str, body: str):
        notifications.append({"title": title, "body": body})

    monkeypatch.setattr("runtime.scheduler_watchdog.send_bark_notification", capture)

    result = run_scheduler_watchdog(paths, push=True)

    assert result.status == "FAILED"
    assert result.issue_count > 0
    assert notifications
    assert notifications[0]["title"] == "量化调度异常"
    assert "daily_trading_pipeline 未成功运行" in notifications[0]["body"]
    assert "建议" in notifications[0]["body"]


def test_scheduler_watchdog_accepts_requested_trade_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """补跑巡检时应能指定历史交易日，而不是硬查当天。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_success_state(paths, "20260707")
    _seed_success_state(paths, "20260708")

    monkeypatch.setattr("runtime.scheduler_watchdog._today", lambda: "20260708")

    result = run_scheduler_watchdog(paths, push=True, trade_date="20260707")

    assert result.trade_date == "20260707"
    assert result.status == "SUCCESS"


def test_scheduler_watchdog_reports_incomplete_strategy_commit(tmp_path: Path) -> None:
    """跨库存储提交未完成时，稳定性巡检必须明确报出检查点。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_success_state(paths, "20260717")
    journal = StrategyCommitJournalRepository(paths.system_state_path)
    lease = journal.begin("quality_overlay", "20260717", "run-1", "code-a", "data-a")
    journal.checkpoint(lease.commit_id, "ADAPTER_PERSISTED")
    journal.fail(lease.commit_id, "paper unavailable")

    result = run_scheduler_watchdog(paths, trade_date="20260717")

    assert result.status == "FAILED"
    assert "策略提交未完成: quality_overlay 20260717 FAILED@ADAPTER_PERSISTED" in result.issues


def _seed_success_state(paths: RuntimePaths, trade_date: str) -> None:
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    register_builtin_strategy_instances(repository)
    run_dir = paths.runs_dir / trade_date
    repository.record_strategy_run("daily_trading_pipeline", trade_date, "SUCCESS", run_dir, "ok")
    for sequence, step_name in enumerate(["data_update", "data_notification", "strategy_batch", "notification"], start=1):
        repository.record_run_step("daily_trading_pipeline", trade_date, sequence, step_name, "SUCCESS", "ok")
    for strategy_id in ["quality_overlay", "mainline_chain_factor_v1", "innovative_drug_globalization_observer_v0"]:
        repository.record_strategy_run(strategy_id, trade_date, "SUCCESS", run_dir, "ok")
    repository.record_research_monitor_run("theme_a", trade_date, "SUCCESS", "ok", {"upgrade_candidate": False})
    repository.record_opportunity_direction_ranking(
        trade_date,
        {"theme_id": "theme_a", "name": "主题A", "status": "observation", "stage": "Seed"},
        {"strength_score": 1.0, "upgrade_candidate": False},
        "ok",
    )
    latest_date = pd.to_datetime(trade_date, format="%Y%m%d")
    dates = pd.to_datetime([latest_date - pd.Timedelta(days=1), latest_date])
    monitoring = MonitoringRepository(paths.monitoring_path)
    for strategy_id in ["quality_overlay", "mainline_chain_factor_v1", "innovative_drug_globalization_observer_v0"]:
        monitoring.upsert_strategy_daily(
            build_strategy_monitor_frame(
                strategy_id=strategy_id,
                strategy_name=strategy_id,
                daily_values=pd.Series([100.0, 101.0], index=dates),
                benchmark_values=pd.Series([1.0, 1.0], index=dates),
                exposure=pd.Series([1.0, 1.0], index=dates),
            )
        )
