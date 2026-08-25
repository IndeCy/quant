"""策略运行契约与执行器注册表测试。"""

from pathlib import Path

import pytest

from domain.strategy_execution import StrategyExecutionResult, TargetPortfolio, TargetPosition
from runtime.paths import RuntimePaths
from runtime.strategy_executor_registry import StrategyExecutionContext, StrategyExecutorRegistry


def test_target_portfolio_validates_weights_and_exposure() -> None:
    """目标组合必须使用合法权重，并明确组合目标暴露。"""
    portfolio = TargetPortfolio(
        strategy_id="quality_v1",
        trade_date="20260715",
        positions=(
            TargetPosition(symbol="000001.SZ", target_weight=0.4),
            TargetPosition(symbol="000002.SZ", target_weight=0.3),
        ),
        target_exposure=0.7,
    )

    assert portfolio.weights == {"000001.SZ": 0.4, "000002.SZ": 0.3}
    rebuilt = TargetPortfolio.from_weights("quality_v1", "20260715", portfolio.weights)
    assert rebuilt == portfolio

    with pytest.raises(ValueError, match="target weights must equal target exposure"):
        TargetPortfolio(
            strategy_id="quality_v1",
            trade_date="20260715",
            positions=(TargetPosition(symbol="000001.SZ", target_weight=0.8),),
            target_exposure=0.7,
        )


def test_execution_registry_prefers_configured_adapter(tmp_path: Path) -> None:
    """兼容执行器由声明配置选择，禁止继续按策略 ID 写特殊分支。"""
    registry = StrategyExecutorRegistry()
    calls: list[str] = []

    def native(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyExecutionResult:
        calls.append("native")
        return StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "native")

    def compat(instance: dict[str, object], context: StrategyExecutionContext) -> StrategyExecutionResult:
        calls.append("compat")
        return StrategyExecutionResult.success(str(instance["strategy_id"]), context.trade_date, "compat")

    registry.register("factor_topn_monthly", native)
    registry.register("quality_overlay_compat", compat)
    context = StrategyExecutionContext(paths=RuntimePaths(tmp_path), trade_date="20260715")
    instance = {
        "strategy_id": "any_quality_name",
        "template_id": "factor_topn_monthly",
        "config": {"adapter": "quality_overlay_compat"},
    }

    result = registry.execute(instance, context)

    assert calls == ["compat"]
    assert result.message == "compat"


def test_execution_registry_rejects_unknown_template(tmp_path: Path) -> None:
    """未登记模板必须显式失败，不能静默降级。"""
    registry = StrategyExecutorRegistry()
    context = StrategyExecutionContext(paths=RuntimePaths(tmp_path), trade_date="20260715")

    with pytest.raises(KeyError, match="unsupported strategy executor"):
        registry.execute({"strategy_id": "unknown", "template_id": "unknown"}, context)
