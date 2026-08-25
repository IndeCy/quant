"""每日流水线 DAG 执行器测试。"""

from __future__ import annotations

import threading
import time

from runtime.pipeline_dag import PipelineDagExecutor, PipelineNode


def test_pipeline_dag_runs_dependencies_in_topological_waves() -> None:
    """质量门禁后，策略与 Beta 观察应进入同一个并行波次。"""
    events: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def record(name: str) -> str:
        with lock:
            events.append(name)
        return name

    def parallel_node(name: str) -> str:
        barrier.wait(timeout=1.0)
        return record(name)

    nodes = [
        PipelineNode("data_update", (), lambda: record("data_update")),
        PipelineNode("data_quality", ("data_update",), lambda: record("data_quality")),
        PipelineNode("strategy_batch", ("data_quality",), lambda: parallel_node("strategy_batch")),
        PipelineNode("market_beta", ("data_quality",), lambda: parallel_node("market_beta")),
    ]

    results = PipelineDagExecutor(max_workers=2).execute(nodes)

    assert results["data_update"].status == "SUCCESS"
    assert results["data_quality"].status == "SUCCESS"
    assert results["strategy_batch"].status == "SUCCESS"
    assert results["market_beta"].status == "SUCCESS"
    assert events[:2] == ["data_update", "data_quality"]
    assert set(events[2:]) == {"strategy_batch", "market_beta"}


def test_pipeline_dag_skips_dependents_after_failure() -> None:
    """前置节点失败时，下游节点必须被明确标记为跳过。"""
    called = False

    def fail_quality() -> None:
        raise RuntimeError("复权因子缺失")

    def run_strategy() -> None:
        nonlocal called
        called = True

    nodes = [
        PipelineNode("data_update", (), lambda: "ok"),
        PipelineNode("data_quality", ("data_update",), fail_quality),
        PipelineNode("strategy_batch", ("data_quality",), run_strategy),
    ]

    results = PipelineDagExecutor(max_workers=2).execute(nodes)

    assert results["data_quality"].status == "FAILED"
    assert isinstance(results["data_quality"].error, RuntimeError)
    assert results["strategy_batch"].status == "SKIPPED"
    assert "data_quality" in results["strategy_batch"].message
    assert called is False


def test_pipeline_dag_rejects_cycles() -> None:
    """循环依赖必须在执行前失败，避免调度任务永久等待。"""
    nodes = [
        PipelineNode("first", ("second",), lambda: None),
        PipelineNode("second", ("first",), lambda: None),
    ]

    try:
        PipelineDagExecutor().execute(nodes)
    except ValueError as exc:
        assert "循环依赖" in str(exc)
    else:
        raise AssertionError("循环依赖未被拒绝")


def test_pipeline_dag_records_node_duration() -> None:
    """节点结果应保留耗时，供运行中心后续展示。"""
    nodes = [PipelineNode("slow", (), lambda: time.sleep(0.01))]

    result = PipelineDagExecutor().execute(nodes)["slow"]

    assert result.duration_seconds >= 0.01


def test_pipeline_dag_serializes_nodes_sharing_a_resource() -> None:
    """同一 SQLite 写资源的节点不能重叠执行。"""
    active_count = 0
    max_active_count = 0
    lock = threading.Lock()

    def write_database() -> None:
        nonlocal active_count, max_active_count
        with lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        time.sleep(0.01)
        with lock:
            active_count -= 1

    nodes = [
        PipelineNode("strategy", (), write_database, resources=("monitoring_sqlite",)),
        PipelineNode("beta", (), write_database, resources=("monitoring_sqlite",)),
    ]

    results = PipelineDagExecutor(max_workers=2).execute(nodes)

    assert all(result.status == "SUCCESS" for result in results.values())
    assert max_active_count == 1
