"""配置化策略执行器注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from domain.strategy_execution import StrategyExecutionResult
from runtime.paths import RuntimePaths


@dataclass(frozen=True)
class StrategyExecutionContext:
    """执行器共享的运行上下文，不包含策略 Alpha 参数。"""

    paths: RuntimePaths
    trade_date: str
    push: bool = False
    bark_url: str = ""
    run_id: str = ""
    code_version: str = ""
    data_version: str = ""
    force_commit: bool = False


@dataclass(frozen=True)
class StrategyComputation:
    """策略纯计算产物；payload 只在对应 adapter 的提交器中解释。"""

    result: StrategyExecutionResult
    payload: object | None = None


StrategyExecutor = Callable[
    [dict[str, Any], StrategyExecutionContext],
    StrategyComputation | StrategyExecutionResult,
]
StrategyPersister = Callable[
    [dict[str, Any], StrategyExecutionContext, StrategyComputation],
    StrategyExecutionResult,
]


class StrategyExecutorRegistry:
    """通过声明式 adapter/template_id 解析执行器。"""

    def __init__(self) -> None:
        self._executors: dict[str, StrategyExecutor] = {}
        self._persisters: dict[str, StrategyPersister] = {}

    def register(
        self,
        executor_id: str,
        executor: StrategyExecutor,
        persister: StrategyPersister | None = None,
    ) -> None:
        """登记执行器，重复 ID 直接失败以避免运行路径被静默覆盖。"""
        key = executor_id.strip()
        if not key:
            raise ValueError("strategy executor id is required")
        if key in self._executors:
            raise ValueError(f"duplicate strategy executor: {key}")
        self._executors[key] = executor
        if persister is not None:
            self._persisters[key] = persister

    def resolve_id(self, instance: dict[str, Any]) -> str:
        """优先读取显式 adapter，否则使用通用模板 ID。"""
        config = dict(instance.get("config") or {})
        return str(config.get("adapter") or instance.get("template_id") or "").strip()

    def compute(self, instance: dict[str, Any], context: StrategyExecutionContext) -> StrategyComputation:
        """只运行策略计算，不触发已登记的持久化动作。"""
        executor_id = self.resolve_id(instance)
        executor = self._executors.get(executor_id)
        if executor is None:
            raise KeyError(f"unsupported strategy executor: {executor_id or '<empty>'}")
        value = executor(instance, context)
        computation = value if isinstance(value, StrategyComputation) else StrategyComputation(result=value)
        self._validate_result(instance, computation.result)
        return computation

    def persist(
        self,
        instance: dict[str, Any],
        context: StrategyExecutionContext,
        computation: StrategyComputation,
    ) -> StrategyExecutionResult:
        """提交一个已完成的计算产物；无专用提交器时直接返回领域结果。"""
        executor_id = self.resolve_id(instance)
        if executor_id not in self._executors:
            raise KeyError(f"unsupported strategy executor: {executor_id or '<empty>'}")
        persister = self._persisters.get(executor_id)
        result = computation.result if persister is None else persister(instance, context, computation)
        self._validate_result(instance, result)
        return result

    def execute(self, instance: dict[str, Any], context: StrategyExecutionContext) -> StrategyExecutionResult:
        """兼容单策略调用：在当前线程依次计算并提交。"""
        computation = self.compute(instance, context)
        return self.persist(instance, context, computation)

    @staticmethod
    def _validate_result(instance: dict[str, Any], result: StrategyExecutionResult) -> None:
        strategy_id = str(instance.get("strategy_id") or "")
        if result.strategy_id != strategy_id:
            raise ValueError(
                f"strategy execution result mismatch: expected {strategy_id}, got {result.strategy_id}"
            )
