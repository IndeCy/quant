"""轻量级每日流水线 DAG 执行器。

该模块只负责编排节点依赖和受控并行，不承载任何策略或数据业务逻辑。
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable, Literal


PipelineStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]


@dataclass(frozen=True)
class PipelineNode:
    """一个可执行流水线节点及其直接依赖。"""

    node_id: str
    dependencies: tuple[str, ...]
    executor: Callable[[], object]
    resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineNodeResult:
    """节点执行结果，失败异常保留给上层统一处理。"""

    node_id: str
    status: PipelineStatus
    value: object | None = None
    error: Exception | None = None
    message: str = ""
    duration_seconds: float = 0.0


class PipelineDagExecutor:
    """按拓扑波次执行节点，同一波次使用受限线程池并行。"""

    def __init__(self, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers 必须大于 0")
        self.max_workers = max_workers

    def execute(self, nodes: list[PipelineNode]) -> dict[str, PipelineNodeResult]:
        """执行完整 DAG；业务失败会写入结果，不会中断独立分支。"""
        node_map = self._validate(nodes)
        pending = dict(node_map)
        results: dict[str, PipelineNodeResult] = {}
        resource_locks = {
            resource: Lock()
            for node in nodes
            for resource in node.resources
        }

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="quant-pipeline") as pool:
            while pending:
                ready = [
                    node
                    for node in pending.values()
                    if all(dependency in results for dependency in node.dependencies)
                ]
                if not ready:
                    unresolved = ", ".join(sorted(pending))
                    raise ValueError(f"流水线存在循环依赖: {unresolved}")

                runnable: list[PipelineNode] = []
                for node in ready:
                    failed_dependencies = [
                        dependency
                        for dependency in node.dependencies
                        if results[dependency].status != "SUCCESS"
                    ]
                    if failed_dependencies:
                        results[node.node_id] = PipelineNodeResult(
                            node_id=node.node_id,
                            status="SKIPPED",
                            message="前置节点未成功: " + ", ".join(failed_dependencies),
                        )
                    else:
                        runnable.append(node)
                    pending.pop(node.node_id)

                futures: dict[str, Future[PipelineNodeResult]] = {
                    node.node_id: pool.submit(self._execute_node, node, resource_locks) for node in runnable
                }
                for node in runnable:
                    results[node.node_id] = futures[node.node_id].result()

        return results

    @staticmethod
    def _execute_node(node: PipelineNode, resource_locks: dict[str, Lock]) -> PipelineNodeResult:
        """执行单节点并把业务异常转换为结构化失败。"""
        started = monotonic()
        try:
            # 多资源按名称排序获取，防止节点间反向加锁形成死锁。
            with ExitStack() as stack:
                for resource in sorted(set(node.resources)):
                    stack.enter_context(resource_locks[resource])
                value = node.executor()
        except Exception as exc:
            return PipelineNodeResult(
                node_id=node.node_id,
                status="FAILED",
                error=exc,
                message=str(exc),
                duration_seconds=monotonic() - started,
            )
        return PipelineNodeResult(
            node_id=node.node_id,
            status="SUCCESS",
            value=value,
            duration_seconds=monotonic() - started,
        )

    @staticmethod
    def _validate(nodes: list[PipelineNode]) -> dict[str, PipelineNode]:
        """校验节点 ID 和依赖引用，不允许隐式缺失节点。"""
        node_map = {node.node_id: node for node in nodes}
        if len(node_map) != len(nodes):
            raise ValueError("流水线节点 ID 不能重复")
        missing = {
            dependency
            for node in nodes
            for dependency in node.dependencies
            if dependency not in node_map
        }
        if missing:
            raise ValueError("流水线依赖节点不存在: " + ", ".join(sorted(missing)))
        return node_map
