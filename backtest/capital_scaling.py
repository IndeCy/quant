"""
资本规模与实盘可行性分析。

该模块用于评估不同资金规模下的可扩展性、稳定性和可交易性边界。
它只消费收益、权重和市场成交额数据，不修改 M0 执行层，也不改变策略逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd


@dataclass(frozen=True)
class CapitalScalingResult:
    """单个资金规模下的模拟结果。"""

    capital: float
    total_return: float
    max_drawdown: float
    turnover: float
    execution_cost: float


@dataclass(frozen=True)
class LiquidityStressResult:
    """流动性压力测试结果。"""

    untradable_ratio: float
    execution_failure_rate: float
    untradable_symbols: list[str]


@dataclass(frozen=True)
class ExecutionCostCurveResult:
    """执行成本曲线分析结果。"""

    cost_bps_by_capital: dict[float, float]
    shape: str
    break_point: float | None


@dataclass(frozen=True)
class FragilityResult:
    """组合脆弱性压力结果。"""

    base_max_drawdown: float
    stressed_max_drawdown: float
    drawdown_change: float
    recovery_time: int


@dataclass(frozen=True)
class StabilityResult:
    """规模稳定性分析结果。"""

    turnover_instability: float
    top_holdings_stability: float
    signal_consistency: float


class CapitalScalingSimulator:
    """按资金规模模拟收益、回撤、换手和执行成本。"""

    def __init__(
        self,
        scales: list[float] | None = None,
        max_amount_participation: float = 0.10,
        base_cost_bps: float = 5.0,
    ) -> None:
        self.scales = scales or [100_000, 500_000, 1_000_000, 5_000_000]
        self.max_amount_participation = float(max_amount_participation)
        self.base_cost_bps = float(base_cost_bps)

    def simulate(
        self,
        returns: pd.Series,
        weights: dict[str, float],
        market_data: pd.DataFrame,
        turnover: float,
    ) -> list[CapitalScalingResult]:
        """对多档资金规模输出核心可交易性指标。"""
        total_return = self._total_return(returns)
        max_drawdown = self._max_drawdown(returns)
        results = []
        for capital in self.scales:
            liquidity = LiquidityStressTester(self.max_amount_participation).run(capital, weights, market_data)
            execution_cost = self._execution_cost(capital, turnover, liquidity.execution_failure_rate)
            results.append(
                CapitalScalingResult(
                    capital=float(capital),
                    total_return=total_return,
                    max_drawdown=max_drawdown,
                    turnover=float(turnover),
                    execution_cost=execution_cost,
                )
            )
        return results

    def _execution_cost(self, capital: float, turnover: float, failure_rate: float) -> float:
        """执行成本随资金规模和失败率上升，不用于收益优化。"""
        base = float(capital) * float(turnover) * self.base_cost_bps / 10_000
        stress_multiplier = 1 + 4 * float(failure_rate)
        return base * stress_multiplier

    def _total_return(self, returns: pd.Series) -> float:
        curve = (1 + returns.astype(float)).cumprod()
        return float(curve.iloc[-1] - 1) if not curve.empty else 0.0

    def _max_drawdown(self, returns: pd.Series) -> float:
        curve = (1 + returns.astype(float)).cumprod()
        if curve.empty:
            return 0.0
        running_max = curve.expanding().max()
        return float(((curve - running_max) / running_max).min())


class LiquidityStressTester:
    """成交额限制、个股容量和无法成交压力测试。"""

    def __init__(self, max_amount_participation: float = 0.10) -> None:
        self.max_amount_participation = float(max_amount_participation)

    def run(self, capital: float, weights: dict[str, float], market_data: pd.DataFrame) -> LiquidityStressResult:
        """输出不可交易股票比例和成交失败率。"""
        if not weights:
            return LiquidityStressResult(0.0, 0.0, [])
        frame = market_data.set_index("symbol")
        untradable: list[str] = []
        failed_notional = 0.0
        total_notional = 0.0
        for symbol, weight in weights.items():
            requested = abs(float(capital) * float(weight))
            total_notional += requested
            amount = float(frame.loc[symbol, "amount"]) if symbol in frame.index else 0.0
            capacity = amount * self.max_amount_participation
            if requested > capacity:
                untradable.append(symbol)
                failed_notional += requested - capacity
        return LiquidityStressResult(
            untradable_ratio=len(untradable) / len(weights),
            execution_failure_rate=failed_notional / total_notional if total_notional else 0.0,
            untradable_symbols=untradable,
        )


class ExecutionCostCurve:
    """资金规模 vs 执行成本曲线分析。"""

    def __init__(self, nonlinear_threshold: float = 2.0) -> None:
        self.nonlinear_threshold = float(nonlinear_threshold)

    def analyze(self, capitals: list[float], execution_costs: list[float]) -> ExecutionCostCurveResult:
        """判断成本曲线是否出现非线性增长和 break point。"""
        cost_bps = {
            float(capital): float(cost) / float(capital) * 10_000
            for capital, cost in zip(capitals, execution_costs)
            if capital > 0
        }
        values = list(cost_bps.items())
        base_bps = values[0][1] if values else 0.0
        break_point = None
        for capital, bps in values[1:]:
            if base_bps > 0 and bps / base_bps >= self.nonlinear_threshold:
                break_point = capital
                break
        shape = "NON_LINEAR" if break_point is not None else "LINEAR"
        return ExecutionCostCurveResult(cost_bps, shape, break_point)


class PortfolioFragilityTester:
    """单标的、行业集中和市场极端冲击测试。"""

    def run(
        self,
        returns: pd.Series,
        weights: dict[str, float],
        industry_map: dict[str, str],
        shock_symbol: str,
        shock_industry: str,
    ) -> dict[str, FragilityResult]:
        """输出三类压力场景的回撤变化和恢复时间。"""
        base_drawdown = self._max_drawdown(returns)
        single_weight = weights.get(shock_symbol, 0.0)
        industry_weight = sum(weight for symbol, weight in weights.items() if industry_map.get(symbol) == shock_industry)
        return {
            "single_symbol": self._scenario(returns, base_drawdown, -0.20 * single_weight),
            "industry": self._scenario(returns, base_drawdown, -0.15 * industry_weight),
            "market_extreme": self._scenario(returns, base_drawdown, -0.08),
        }

    def _scenario(self, returns: pd.Series, base_drawdown: float, shock: float) -> FragilityResult:
        stressed = returns.astype(float).copy()
        if not stressed.empty:
            shock_index = 1 if len(stressed) > 1 else 0
            stressed.iloc[shock_index] = stressed.iloc[shock_index] + shock
        stressed_drawdown = self._max_drawdown(stressed)
        return FragilityResult(
            base_max_drawdown=base_drawdown,
            stressed_max_drawdown=stressed_drawdown,
            drawdown_change=stressed_drawdown - base_drawdown,
            recovery_time=self._recovery_time(stressed),
        )

    def _max_drawdown(self, returns: pd.Series) -> float:
        curve = (1 + returns.astype(float)).cumprod()
        if curve.empty:
            return 0.0
        running_max = curve.expanding().max()
        return float(((curve - running_max) / running_max).min())

    def _recovery_time(self, returns: pd.Series) -> int:
        curve = (1 + returns.astype(float)).cumprod()
        if curve.empty:
            return 0
        peak = float(curve.iloc[0])
        trough_index = int(((curve - curve.expanding().max()) / curve.expanding().max()).idxmin())
        post_trough = curve.iloc[trough_index:]
        recovered = post_trough[post_trough >= peak]
        if recovered.empty:
            return len(post_trough) - 1
        return int(recovered.index[0] - trough_index)


class ScalingStabilityAnalyzer:
    """资金规模变化下的换手、头部持仓和信号一致性分析。"""

    def analyze(
        self,
        turnover_by_scale: dict[float, float],
        holdings_by_scale: dict[float, list[str]],
        signals_by_scale: dict[float, dict[str, float]],
    ) -> StabilityResult:
        """输出三类稳定性指标。"""
        turnover_values = [float(value) for _, value in sorted(turnover_by_scale.items())]
        turnover_instability = self._std(turnover_values)
        top_holdings_stability = self._average_jaccard([set(value) for _, value in sorted(holdings_by_scale.items())])
        signal_consistency = self._signal_consistency([value for _, value in sorted(signals_by_scale.items())])
        return StabilityResult(turnover_instability, top_holdings_stability, signal_consistency)

    def _std(self, values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))

    def _average_jaccard(self, holdings: list[set[str]]) -> float:
        if len(holdings) < 2:
            return 1.0
        scores = []
        for previous, current in zip(holdings, holdings[1:]):
            union = previous | current
            scores.append(len(previous & current) / len(union) if union else 1.0)
        return sum(scores) / len(scores)

    def _signal_consistency(self, signals: list[dict[str, float]]) -> float:
        if len(signals) < 2:
            return 1.0
        scores = []
        for previous, current in zip(signals, signals[1:]):
            symbols = set(previous) | set(current)
            if not symbols:
                scores.append(1.0)
                continue
            diff = sum(abs(previous.get(symbol, 0.0) - current.get(symbol, 0.0)) for symbol in symbols)
            scale = sum(abs(previous.get(symbol, 0.0)) + abs(current.get(symbol, 0.0)) for symbol in symbols) or 1.0
            scores.append(max(1.0 - diff / scale, 0.0))
        return sum(scores) / len(scores)
