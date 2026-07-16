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


StrategyExecutor = Callable[[dict[str, Any], StrategyExecutionContext], StrategyExecutionResult]


class StrategyExecutorRegistry:
    """通过声明式 adapter/template_id 解析执行器。"""

    def __init__(self) -> None:
        self._executors: dict[str, StrategyExecutor] = {}

    def register(self, executor_id: str, executor: StrategyExecutor) -> None:
        """登记执行器，重复 ID 直接失败以避免运行路径被静默覆盖。"""
        key = executor_id.strip()
        if not key:
            raise ValueError("strategy executor id is required")
        if key in self._executors:
            raise ValueError(f"duplicate strategy executor: {key}")
        self._executors[key] = executor

    def resolve_id(self, instance: dict[str, Any]) -> str:
        """优先读取显式 adapter，否则使用通用模板 ID。"""
        config = dict(instance.get("config") or {})
        return str(config.get("adapter") or instance.get("template_id") or "").strip()

    def execute(self, instance: dict[str, Any], context: StrategyExecutionContext) -> StrategyExecutionResult:
        """解析并运行策略执行器。"""
        executor_id = self.resolve_id(instance)
        executor = self._executors.get(executor_id)
        if executor is None:
            raise KeyError(f"unsupported strategy executor: {executor_id or '<empty>'}")
        return executor(instance, context)
