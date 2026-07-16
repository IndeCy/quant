"""R3 策略提交日志与中断恢复测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.strategy_execution import StrategyExecutionResult, TargetPortfolio
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import execute_strategy_instances
from runtime.strategy_commit_journal import StrategyCommitJournalRepository
from runtime.strategy_executor_registry import StrategyComputation, StrategyExecutionContext, StrategyExecutorRegistry


def _instance() -> dict[str, object]:
    return {
        "strategy_id": "recoverable_alpha",
        "name": "Recoverable Alpha",
        "template_id": "recoverable",
        "benchmark": "510300",
        "config": {},
    }


def test_commit_journal_resumes_and_force_resets(tmp_path: Path) -> None:
    """失败提交应保留检查点；完成后默认跳过，force 才从头重放。"""
    journal = StrategyCommitJournalRepository(tmp_path / "state.sqlite")

    first = journal.begin("recoverable_alpha", "20260717", "run-1", "code-a", "data-a")
    journal.checkpoint(first.commit_id, "ADAPTER_PERSISTED")
    journal.fail(first.commit_id, "paper unavailable")
    resumed = journal.begin("recoverable_alpha", "20260717", "run-2", "code-a", "data-a")

    assert resumed.resumed is True
    assert resumed.skip is False
    assert resumed.last_step == "ADAPTER_PERSISTED"
    assert resumed.attempt_count == 2

    journal.complete(resumed.commit_id)
    skipped = journal.begin("recoverable_alpha", "20260717", "run-3", "code-a", "data-a")
    forced = journal.begin("recoverable_alpha", "20260717", "run-4", "code-a", "data-a", force=True)

    assert skipped.skip is True
    assert forced.skip is False
    assert forced.resumed is False
    assert forced.last_step == "BEGIN"
    assert forced.attempt_count == 3


def test_strategy_commit_recovers_after_paper_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adapter 已落盘后 Paper 失败，下一次运行应从 Paper 阶段继续。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    registry = StrategyExecutorRegistry()
    persist_calls: list[str] = []
    paper_calls: list[str] = []

    def compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        portfolio = TargetPortfolio.from_weights(
            str(instance["strategy_id"]), context.trade_date, {"000001.SZ": 1.0}
        )
        return StrategyComputation(
            StrategyExecutionResult.success(
                str(instance["strategy_id"]), context.trade_date, "computed", target_portfolio=portfolio
            )
        )

    def persist(
        instance: dict[str, object], context: StrategyExecutionContext, computation: StrategyComputation
    ) -> StrategyExecutionResult:
        persist_calls.append(context.run_id)
        return computation.result

    def sync_once(*_: object, **__: object) -> str:
        paper_calls.append("paper")
        if len(paper_calls) == 1:
            raise RuntimeError("paper unavailable")
        return "paper recovered"

    registry.register("recoverable", compute, persist)
    monkeypatch.setattr("runtime.strategy_batch_runner._sync_target_portfolio", sync_once)

    failed = execute_strategy_instances(
        [_instance()], paths, repository, registry, "20260717", run_id="run-1"
    )
    recovered = execute_strategy_instances(
        [_instance()], paths, repository, registry, "20260717", run_id="run-2"
    )

    assert failed["failed_count"] == 1
    assert recovered["success_count"] == 1
    assert recovered["recovered_count"] == 1
    assert persist_calls == ["run-1"]
    assert paper_calls == ["paper", "paper"]
    row = StrategyCommitJournalRepository(paths.system_state_path).get("recoverable_alpha", "20260717")
    assert row is not None
    assert row["status"] == "COMPLETED"
    assert row["pipeline_run_id"] == "run-2"


def test_completed_commit_is_idempotent_until_forced(tmp_path: Path) -> None:
    """同一策略交易日完成后不能重复提交，明确 force 时允许重放。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    registry = StrategyExecutorRegistry()
    persist_calls: list[str] = []

    def compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        return StrategyComputation(
            StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "computed")
        )

    def persist(
        instance: dict[str, object], context: StrategyExecutionContext, computation: StrategyComputation
    ) -> StrategyExecutionResult:
        persist_calls.append(context.run_id)
        return computation.result

    registry.register("recoverable", compute, persist)
    execute_strategy_instances([_instance()], paths, repository, registry, "20260717", run_id="run-1")
    skipped = execute_strategy_instances([_instance()], paths, repository, registry, "20260717", run_id="run-2")
    forced = execute_strategy_instances(
        [_instance()], paths, repository, registry, "20260717", run_id="run-3", force_commit=True
    )

    assert skipped["idempotent_count"] == 1
    assert forced["success_count"] == 1
    assert persist_calls == ["run-1", "run-3"]


def test_incomplete_commit_restarts_when_versions_change(tmp_path: Path) -> None:
    """代码或数据版本变化后不能跨版本续接旧检查点。"""
    journal = StrategyCommitJournalRepository(tmp_path / "state.sqlite")
    first = journal.begin("recoverable_alpha", "20260717", "run-1", "code-a", "data-a")
    journal.checkpoint(first.commit_id, "PAPER_SYNCED")
    journal.fail(first.commit_id, "interrupted")

    lease = journal.begin("recoverable_alpha", "20260717", "run-2", "code-b", "data-a")

    assert lease.resumed is False
    assert lease.last_step == "BEGIN"
    assert lease.attempt_count == 2


def test_notification_is_not_duplicated_after_completion_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """通知已进入派发检查点后即使终态写入失败，恢复时也不得重复推送。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    registry = StrategyExecutorRegistry()
    persist_calls: list[str] = []
    notification_calls: list[str] = []

    def compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        return StrategyComputation(
            StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "computed")
        )

    def persist(
        instance: dict[str, object], context: StrategyExecutionContext, computation: StrategyComputation
    ) -> StrategyExecutionResult:
        persist_calls.append(context.run_id)
        return computation.result

    registry.register("recoverable", compute, persist)
    monkeypatch.setattr(
        "runtime.strategy_batch_runner._send_native_notification",
        lambda instance, message, push, bark_url: notification_calls.append(message),
    )
    original_complete = StrategyCommitJournalRepository.complete
    complete_calls = 0

    def fail_first_complete(self: StrategyCommitJournalRepository, commit_id: str) -> None:
        nonlocal complete_calls
        complete_calls += 1
        if complete_calls == 1:
            raise RuntimeError("completion write interrupted")
        original_complete(self, commit_id)

    monkeypatch.setattr(StrategyCommitJournalRepository, "complete", fail_first_complete)

    failed = execute_strategy_instances(
        [_instance()], paths, repository, registry, "20260717", run_id="run-1", push=True, bark_url="test"
    )
    recovered = execute_strategy_instances(
        [_instance()], paths, repository, registry, "20260717", run_id="run-2", push=True, bark_url="test"
    )

    assert failed["failed_count"] == 1
    assert recovered["recovered_count"] == 1
    assert persist_calls == ["run-1"]
    assert notification_calls == ["computed"]
