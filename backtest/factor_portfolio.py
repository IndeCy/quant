"""
Milestone 2 因子资产组合化。

该模块是策略层之后、回测执行之前的独立组合层。策略只输出 signal，
本模块负责把 Core/Satellite 信号转换成目标权重。
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FactorPortfolioResult:
    """Core-Satellite 组合构建结果。"""

    target_weights: dict[str, float]
    core_weights: dict[str, float]
    satellite_weights: dict[str, float]
    turnover: float
    raw_turnover: float
    turnover_constraint_applied: bool
    risk_budget: dict[str, float]
    satellite_alpha_scores: dict[str, float]


class CoreSatelliteFactorPortfolio:
    """
    Core-Satellite 因子组合构建器。

    Core 默认 70%，Satellite 默认 30%。信号只决定候选集合，具体权重由
    allocation control、turnover constraint 和简单风险预算共同决定。
    """

    def __init__(
        self,
        core_allocation: float = 0.70,
        satellite_allocation: float = 0.30,
        max_turnover: float = 0.35,
        max_symbol_weight: float = 1.0,
        min_risk: float = 1e-6,
        satellite_weighting: str = "softmax",
        satellite_temperature: float = 1.0,
        satellite_turnover_penalty: float = 1.0,
    ):
        if core_allocation < 0 or satellite_allocation < 0:
            raise ValueError("Core 和 Satellite 配置比例不能为负数")
        if core_allocation + satellite_allocation <= 0:
            raise ValueError("Core 和 Satellite 配置比例之和必须大于0")
        if not 0 <= max_turnover <= 1:
            raise ValueError("max_turnover 必须在 0 到 1 之间")
        if max_symbol_weight <= 0:
            raise ValueError("max_symbol_weight 必须大于0")
        if satellite_weighting not in {"softmax", "linear"}:
            raise ValueError("satellite_weighting 仅支持 softmax/linear")
        if satellite_temperature <= 0:
            raise ValueError("satellite_temperature 必须大于0")
        self.core_allocation = core_allocation
        self.satellite_allocation = satellite_allocation
        self.max_turnover = max_turnover
        self.max_symbol_weight = max_symbol_weight
        self.min_risk = min_risk
        self.satellite_weighting = satellite_weighting
        self.satellite_temperature = satellite_temperature
        self.satellite_turnover_penalty = satellite_turnover_penalty

    def build(
        self,
        core_signals: dict[str, float],
        satellite_signals: dict[str, float],
        risk_estimates: dict[str, float] | None = None,
        previous_weights: dict[str, float] | None = None,
        previous_satellite_signals: dict[str, float] | None = None,
    ) -> FactorPortfolioResult:
        """把 Core/Satellite 信号构造成组合目标权重。"""
        risk_estimates = risk_estimates or {}
        previous_weights = previous_weights or {}
        core_candidates = self._positive_symbols(core_signals)
        satellite_candidates = self._positive_symbols(satellite_signals)
        core_budget, satellite_budget = self._active_budgets(core_candidates, satellite_candidates)

        core_weights = self._risk_budget_weights(core_candidates, core_budget, risk_estimates)
        satellite_weights, satellite_scores = self._satellite_alpha_weights(
            satellite_signals,
            satellite_candidates,
            satellite_budget,
            risk_estimates,
            previous_satellite_signals or {},
        )
        desired = self._merge_weights(core_weights, satellite_weights)
        desired = self._normalize(desired)

        raw_turnover = self._turnover(previous_weights, desired)
        constrained = desired
        applied = False
        if previous_weights and raw_turnover > self.max_turnover:
            applied = True
            scale = self.max_turnover / raw_turnover if raw_turnover else 0.0
            constrained = self._blend(previous_weights, desired, scale)
            constrained = self._normalize(constrained)

        turnover = self._turnover(previous_weights, constrained)
        risk_budget = {
            symbol: self._inverse_risk_score(risk_estimates, symbol)
            for symbol in constrained
            if constrained[symbol] > 0
        }
        return FactorPortfolioResult(
            target_weights=constrained,
            core_weights=core_weights,
            satellite_weights=satellite_weights,
            turnover=turnover,
            raw_turnover=raw_turnover,
            turnover_constraint_applied=applied,
            risk_budget=risk_budget,
            satellite_alpha_scores=satellite_scores,
        )

    def _positive_symbols(self, signals: dict[str, float]) -> list[str]:
        """只把正向信号纳入候选，信号大小不直接等于权重。"""
        return [symbol for symbol, signal in signals.items() if signal > 0]

    def _active_budgets(self, core: list[str], satellite: list[str]) -> tuple[float, float]:
        """根据可用 sleeve 分配预算，缺失 sleeve 时资金留给另一侧。"""
        if core and satellite:
            total = self.core_allocation + self.satellite_allocation
            return self.core_allocation / total, self.satellite_allocation / total
        if core:
            return 1.0, 0.0
        if satellite:
            return 0.0, 1.0
        return 0.0, 0.0

    def _risk_budget_weights(
        self,
        symbols: list[str],
        budget: float,
        risk_estimates: dict[str, float],
    ) -> dict[str, float]:
        """按波动率倒数做简单风险预算。"""
        if not symbols or budget <= 0:
            return {}
        scores = {
            symbol: self._inverse_risk_score(risk_estimates, symbol)
            for symbol in symbols
        }
        total_score = sum(scores.values())
        raw = {
            symbol: budget * score / total_score
            for symbol, score in scores.items()
        }
        return self._cap_and_redistribute(raw, budget)

    def _satellite_alpha_weights(
        self,
        signals: dict[str, float],
        symbols: list[str],
        budget: float,
        risk_estimates: dict[str, float],
        previous_signals: dict[str, float],
    ) -> tuple[dict[str, float], dict[str, float]]:
        """
        Satellite alpha 加权。

        分数 = rank/信号强度映射 * 波动率缩放 * 信号变化惩罚。
        """
        if not symbols or budget <= 0:
            return {}, {}
        confidence = self._satellite_confidence_scores(signals, symbols)
        scores: dict[str, float] = {}
        for symbol in symbols:
            volatility_scale = self._inverse_risk_score(risk_estimates, symbol)
            if previous_signals:
                previous = float(previous_signals.get(symbol, 0.0))
                current = float(signals.get(symbol, 0.0))
                change = abs(current - previous)
                turnover_scale = math.exp(-self.satellite_turnover_penalty * change)
            else:
                turnover_scale = 1.0
            scores[symbol] = confidence[symbol] * volatility_scale * turnover_scale
        total = sum(scores.values())
        if total <= 0:
            return {}, scores
        raw = {symbol: budget * score / total for symbol, score in scores.items()}
        return self._cap_and_redistribute(raw, budget), scores

    def _satellite_confidence_scores(self, signals: dict[str, float], symbols: list[str]) -> dict[str, float]:
        """把 Satellite 信号强度映射成连续 confidence score。"""
        positive = {symbol: max(float(signals.get(symbol, 0.0)), 0.0) for symbol in symbols}
        if self.satellite_weighting == "linear":
            total = sum(positive.values())
            if total <= 0:
                return {symbol: 1.0 for symbol in symbols}
            return {symbol: positive[symbol] / total for symbol in symbols}

        max_signal = max(positive.values()) if positive else 0.0
        exp_scores = {
            symbol: math.exp((positive[symbol] - max_signal) / self.satellite_temperature)
            for symbol in symbols
        }
        return exp_scores

    def _cap_and_redistribute(self, weights: dict[str, float], budget: float) -> dict[str, float]:
        """应用单票上限，剩余预算在未触顶标的之间再分配。"""
        if not weights:
            return {}
        capped = {symbol: 0.0 for symbol in weights}
        remaining = budget
        active = set(weights)
        base = weights.copy()
        while active and remaining > 1e-12:
            active_total = sum(base[symbol] for symbol in active)
            if active_total <= 0:
                equal = remaining / len(active)
                for symbol in list(active):
                    add = min(equal, self.max_symbol_weight - capped[symbol])
                    capped[symbol] += add
                    remaining -= add
                    active.remove(symbol)
                break
            changed = False
            for symbol in list(active):
                add = remaining * base[symbol] / active_total
                capacity = self.max_symbol_weight - capped[symbol]
                if add >= capacity:
                    capped[symbol] += capacity
                    remaining -= capacity
                    active.remove(symbol)
                    changed = True
            if not changed:
                for symbol in list(active):
                    add = remaining * base[symbol] / active_total
                    capped[symbol] += add
                remaining = 0.0
        return {symbol: weight for symbol, weight in capped.items() if weight > 1e-12}

    def _merge_weights(self, *parts: dict[str, float]) -> dict[str, float]:
        merged: dict[str, float] = {}
        for part in parts:
            for symbol, weight in part.items():
                merged[symbol] = merged.get(symbol, 0.0) + weight
        return {symbol: weight for symbol, weight in merged.items() if weight > 1e-12}

    def _normalize(self, weights: dict[str, float]) -> dict[str, float]:
        total = sum(max(weight, 0.0) for weight in weights.values())
        if total <= 0:
            return {}
        return {
            symbol: max(weight, 0.0) / total
            for symbol, weight in weights.items()
            if weight > 1e-12
        }

    def _inverse_risk_score(self, risk_estimates: dict[str, float], symbol: str) -> float:
        """把异常波动率统一视为保守默认风险，避免 NaN 权重外溢。"""
        raw_value = float(risk_estimates.get(symbol, 1.0))
        risk = raw_value if math.isfinite(raw_value) and raw_value > 0 else 1.0
        return 1.0 / max(risk, self.min_risk)

    def _blend(self, previous: dict[str, float], desired: dict[str, float], scale: float) -> dict[str, float]:
        symbols = set(previous) | set(desired)
        return {
            symbol: previous.get(symbol, 0.0) + (desired.get(symbol, 0.0) - previous.get(symbol, 0.0)) * scale
            for symbol in symbols
        }

    def _turnover(self, previous: dict[str, float], current: dict[str, float]) -> float:
        symbols = set(previous) | set(current)
        return 0.5 * sum(abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols)
