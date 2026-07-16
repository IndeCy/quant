"""策略计算结果的幂等串行提交协调器。"""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from typing import Any, Callable

from domain.strategy_execution import StrategyExecutionResult, TargetPortfolio
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_commit_journal import StrategyCommitJournalRepository, step_completed
from runtime.strategy_executor_registry import StrategyComputation, StrategyExecutionContext, StrategyExecutorRegistry


PaperSync = Callable[[dict[str, Any], RuntimePaths, TargetPortfolio], str]
NotificationSender = Callable[[dict[str, Any], str], None]


class StrategyCommitCoordinator:
    """按固定检查点提交策略结果，并在失败后支持幂等续接。"""

    def __init__(
        self,
        paths: RuntimePaths,
        repository: SystemRepository,
        journal: StrategyCommitJournalRepository,
        executors: StrategyExecutorRegistry,
        paper_sync: PaperSync,
        notification_sender: NotificationSender,
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.journal = journal
        self.executors = executors
        self.paper_sync = paper_sync
        self.notification_sender = notification_sender

    def commit(
        self,
        instance: dict[str, Any],
        context: StrategyExecutionContext,
        computation: StrategyComputation,
        compute_duration_seconds: float,
    ) -> dict[str, object]:
        """提交单个计算结果；恢复时跳过已完成检查点。"""
        strategy_id = str(instance["strategy_id"])
        trade_date = computation.result.trade_date
        lease = self.journal.begin(
            strategy_id,
            trade_date,
            context.run_id,
            context.code_version,
            context.data_version,
            force=context.force_commit,
        )
        if lease.skip:
            return {
                **computation.result.to_summary(),
                "phase": "IDEMPOTENT",
                "commit_id": lease.commit_id,
                "recovered": False,
                "idempotent": True,
                "compute_duration_seconds": compute_duration_seconds,
                "persist_duration_seconds": 0.0,
            }

        started = monotonic()
        result = computation.result
        current_step = lease.last_step
        try:
            if not step_completed(current_step, "ADAPTER_PERSISTED"):
                result = self.executors.persist(instance, context, computation)
                self.journal.checkpoint(lease.commit_id, "ADAPTER_PERSISTED")
                current_step = "ADAPTER_PERSISTED"

            if not step_completed(current_step, "PAPER_SYNCED"):
                result = self._sync_paper(instance, result)
                self.journal.checkpoint(lease.commit_id, "PAPER_SYNCED")
                current_step = "PAPER_SYNCED"

            if not step_completed(current_step, "RUN_RECORDED"):
                self.repository.record_strategy_run(
                    strategy_id,
                    result.trade_date,
                    result.status,
                    self.paths.runs_dir / result.trade_date,
                    result.message,
                )
                self.journal.checkpoint(lease.commit_id, "RUN_RECORDED")
                current_step = "RUN_RECORDED"

            if not step_completed(current_step, "NOTIFICATION_DISPATCHING"):
                # 先登记再发送，进程中断恢复时不重复向外部通道推送。
                self.journal.checkpoint(lease.commit_id, "NOTIFICATION_DISPATCHING")
                current_step = "NOTIFICATION_DISPATCHING"
                self.notification_sender(instance, _notification_message(result))

            self.journal.complete(lease.commit_id)
            return {
                **result.to_summary(),
                "phase": "RECOVERED" if lease.resumed else "PERSIST",
                "commit_id": lease.commit_id,
                "recovered": lease.resumed,
                "idempotent": False,
                "compute_duration_seconds": compute_duration_seconds,
                "persist_duration_seconds": monotonic() - started,
            }
        except Exception as exc:
            message = str(exc)
            self.journal.fail(lease.commit_id, message)
            self.repository.record_strategy_run(
                strategy_id,
                trade_date,
                "FAILED",
                self.paths.runs_dir / trade_date,
                message,
            )
            if not step_completed(current_step, "NOTIFICATION_DISPATCHING"):
                self.notification_sender(instance, f"FAILED: {message}")
            return {
                "strategy_id": strategy_id,
                "status": "FAILED",
                "message": message,
                "phase": "PERSIST",
                "commit_id": lease.commit_id,
                "recovered": lease.resumed,
                "idempotent": False,
                "compute_duration_seconds": compute_duration_seconds,
                "persist_duration_seconds": monotonic() - started,
            }

    def _sync_paper(
        self,
        instance: dict[str, Any],
        result: StrategyExecutionResult,
    ) -> StrategyExecutionResult:
        if result.target_portfolio is None:
            return result
        paper_message = self.paper_sync(instance, self.paths, result.target_portfolio)
        return replace(result, message=f"{result.message}; {paper_message}")


def _notification_message(result: StrategyExecutionResult) -> str:
    if result.observation_only:
        return f"{result.message}\n观察策略，不构成调仓建议"
    return result.message
