"""固定资产配置观察策略的运行时适配器。"""

from __future__ import annotations

from typing import Any

from domain.strategy_execution import StrategyExecutionResult
from runtime.strategy_executor_registry import (
    StrategyComputation,
    StrategyExecutionContext,
)
from strategies.fixed_allocation_observer_runner import (
    FixedAllocationObserverComputation,
    compute_fixed_allocation_observer,
    persist_fixed_allocation_observer,
)


def compute_fixed_allocation_observer_adapter(
    instance: dict[str, Any],
    context: StrategyExecutionContext,
) -> StrategyComputation:
    """计算观察净值，但不返回可同步Broker的目标组合。"""
    payload = compute_fixed_allocation_observer(
        instance,
        context.paths,
        context.trade_date,
    )
    result = payload.result
    message = (
        f"observation selected {result['selected_count']} assets, "
        f"nav {result['nav']:.6f}"
    )
    return StrategyComputation(
        result=StrategyExecutionResult.success(
            str(instance["strategy_id"]),
            str(result["trade_date"]),
            message,
            selected_count=int(result["selected_count"]),
            nav=float(result["nav"]),
            observation_only=True,
        ),
        payload=payload,
    )


def persist_fixed_allocation_observer_adapter(
    instance: dict[str, Any],
    context: StrategyExecutionContext,
    computation: StrategyComputation,
) -> StrategyExecutionResult:
    """保存观察产物并保持交易目标为空。"""
    if not isinstance(computation.payload, FixedAllocationObserverComputation):
        raise TypeError(
            "strategy computation payload must be "
            "FixedAllocationObserverComputation"
        )
    persist_fixed_allocation_observer(
        instance,
        context.paths,
        computation.payload,
    )
    return computation.result
