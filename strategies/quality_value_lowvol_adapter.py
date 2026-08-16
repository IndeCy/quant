"""Quality Value LowVol 与统一策略批处理之间的薄适配层。"""

from __future__ import annotations

from typing import Any

from domain.strategy_execution import StrategyExecutionResult, TargetPortfolio
from runtime.strategy_executor_registry import StrategyComputation, StrategyExecutionContext
from strategies.quality_value_lowvol_runner import (
    QualityValueLowVolComputation,
    compute_quality_value_lowvol_instance,
    persist_quality_value_lowvol_instance,
)


def compute_quality_value_lowvol_adapter(
    instance: dict[str, Any],
    context: StrategyExecutionContext,
) -> StrategyComputation:
    """计算研究资产，并仅在目标变化时构造正式 Paper 目标。"""
    payload = compute_quality_value_lowvol_instance(instance, context.paths, context.trade_date)
    result = payload.result
    trade_date = str(result["trade_date"])
    portfolio = None
    if bool(result.get("action_required")):
        names = {
            str(row.symbol): str(row.name)
            for row in payload.holdings.itertuples(index=False)
        }
        reasons = {
            str(row.symbol): str(row.reason)
            for row in payload.holdings.itertuples(index=False)
        }
        portfolio = TargetPortfolio.from_weights(
            str(instance["strategy_id"]),
            trade_date,
            dict(result["target_weights"]),
            names,
            reasons,
        )
    return StrategyComputation(
        result=StrategyExecutionResult.success(
            str(instance["strategy_id"]),
            trade_date,
            str(result["message"]),
            selected_count=int(result["selected_count"]),
            nav=float(result["nav"]),
            target_portfolio=portfolio,
        ),
        payload=payload,
    )


def persist_quality_value_lowvol_adapter(
    instance: dict[str, Any],
    context: StrategyExecutionContext,
    computation: StrategyComputation,
) -> StrategyExecutionResult:
    """把适配器载荷交给唯一策略提交阶段持久化。"""
    if not isinstance(computation.payload, QualityValueLowVolComputation):
        raise TypeError("strategy computation payload must be QualityValueLowVolComputation")
    persist_quality_value_lowvol_instance(instance, context.paths, computation.payload)
    return computation.result
