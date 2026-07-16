"""R2 策略计算与串行提交协议测试。"""

from __future__ import annotations

from pathlib import Path
from threading import Barrier, Lock
import time

from domain.strategy_execution import StrategyExecutionResult
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import execute_strategy_instances
from runtime.strategy_executor_registry import (
    StrategyComputation,
    StrategyExecutionContext,
    StrategyExecutorRegistry,
)


def _instance(strategy_id: str, template_id: str) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "name": strategy_id,
        "template_id": template_id,
        "benchmark": "510300",
        "config": {},
    }


def test_registry_compute_does_not_call_persister(tmp_path: Path) -> None:
    """纯计算阶段不得提前触发状态提交。"""
    events: list[str] = []
    registry = StrategyExecutorRegistry()

    def compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        events.append("compute")
        result = StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "computed")
        return StrategyComputation(result=result, payload={"value": 1})

    def persist(
        instance: dict[str, object], context: StrategyExecutionContext, computation: StrategyComputation
    ) -> StrategyExecutionResult:
        events.append("persist")
        return computation.result

    registry.register("test", compute, persist)
    context = StrategyExecutionContext(RuntimePaths(tmp_path), "20260716")

    computation = registry.compute(_instance("alpha", "test"), context)

    assert events == ["compute"]
    assert computation.result.message == "computed"
    registry.persist(_instance("alpha", "test"), context, computation)
    assert events == ["compute", "persist"]


def test_strategy_batch_computes_in_parallel_and_persists_in_stable_order(tmp_path: Path) -> None:
    """策略计算可并行，但共享状态提交必须按实例顺序串行。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    registry = StrategyExecutorRegistry()
    compute_barrier = Barrier(2)
    state_lock = Lock()
    active_persists = 0
    max_active_persists = 0
    persisted: list[str] = []

    def compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        compute_barrier.wait(timeout=2)
        result = StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "computed")
        return StrategyComputation(result=result)

    def persist(
        instance: dict[str, object], context: StrategyExecutionContext, computation: StrategyComputation
    ) -> StrategyExecutionResult:
        nonlocal active_persists, max_active_persists
        with state_lock:
            active_persists += 1
            max_active_persists = max(max_active_persists, active_persists)
        time.sleep(0.02)
        persisted.append(str(instance["strategy_id"]))
        with state_lock:
            active_persists -= 1
        return computation.result

    registry.register("first", compute, persist)
    registry.register("second", compute, persist)

    summary = execute_strategy_instances(
        [_instance("alpha", "first"), _instance("beta", "second")],
        paths,
        repository,
        registry,
        "20260716",
        max_workers=2,
    )

    assert summary["success_count"] == 2
    assert max_active_persists == 1
    assert persisted == ["alpha", "beta"]
    assert [item["strategy_id"] for item in summary["results"]] == ["alpha", "beta"]


def test_strategy_batch_isolates_compute_failure(tmp_path: Path) -> None:
    """一个策略计算失败时，其他策略仍应完成串行提交。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    registry = StrategyExecutorRegistry()
    persisted: list[str] = []

    def failed_compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        raise RuntimeError("broken alpha")

    def successful_compute(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyComputation:
        return StrategyComputation(
            result=StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "ok")
        )

    def persist(
        instance: dict[str, object], context: StrategyExecutionContext, computation: StrategyComputation
    ) -> StrategyExecutionResult:
        persisted.append(str(instance["strategy_id"]))
        return computation.result

    registry.register("broken", failed_compute, persist)
    registry.register("healthy", successful_compute, persist)

    summary = execute_strategy_instances(
        [_instance("broken_alpha", "broken"), _instance("healthy_alpha", "healthy")],
        paths,
        repository,
        registry,
        "20260716",
        max_workers=2,
    )

    assert summary["success_count"] == 1
    assert summary["failed_count"] == 1
    assert persisted == ["healthy_alpha"]
    assert repository.get_run("broken_alpha", "20260716")["status"] == "FAILED"
    assert repository.get_run("healthy_alpha", "20260716")["status"] == "SUCCESS"
