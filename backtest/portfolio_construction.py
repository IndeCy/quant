"""
组合构建与换手压缩规则。

该模块只处理排名结果到目标权重的转换，不改变任何价格因子定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ConstructionResult:
    """一次调仓的组合构建结果。"""

    target_weights: dict[str, float]
    target_holdings: set[str]
    retained_holdings: set[str]
    satellite_holdings: set[str]
    turnover: float
    replacements: int


class CoreSatelliteTurnoverConstructor:
    """
    Core-Satellite 组合构建器。

    规则：
    - 旧持仓仍在 rank_band 内则优先保留。
    - 每次最多替换 max_replace_ratio * top_n 个标的。
    - 目标组合至少尽量保留 min_retention_ratio * top_n 个旧持仓。
    - 若目标权重换手超过 max_turnover，则继续减少替换数量。
    - Core 权重分配给延续持仓，Satellite 权重分配给新进持仓。
    """

    def __init__(
        self,
        symbols: Iterable[str],
        top_n: int = 20,
        rank_band: int = 40,
        min_retention_ratio: float = 0.60,
        max_replace_ratio: float = 0.40,
        max_turnover: float = 0.40,
        core_weight: float = 0.70,
    ):
        if top_n < 1:
            raise ValueError("top_n 必须大于 0")
        if rank_band < top_n:
            raise ValueError("rank_band 必须大于等于 top_n")
        if not 0 <= min_retention_ratio <= 1:
            raise ValueError("min_retention_ratio 必须在 0 到 1 之间")
        if not 0 <= max_replace_ratio <= 1:
            raise ValueError("max_replace_ratio 必须在 0 到 1 之间")
        if not 0 <= max_turnover <= 1:
            raise ValueError("max_turnover 必须在 0 到 1 之间")
        if not 0 <= core_weight <= 1:
            raise ValueError("core_weight 必须在 0 到 1 之间")
        self.symbols = list(symbols)
        self.top_n = top_n
        self.rank_band = rank_band
        self.min_retention_ratio = min_retention_ratio
        self.max_replace_ratio = max_replace_ratio
        self.max_turnover = max_turnover
        self.core_weight = core_weight

    def build(
        self,
        ranked_symbols: list[str],
        previous_weights: dict[str, float] | None = None,
    ) -> ConstructionResult:
        """根据排名和上期权重构造低换手目标组合。"""
        previous_weights = previous_weights or {}
        previous_holdings = {symbol for symbol, weight in previous_weights.items() if weight > 0}
        if not previous_holdings:
            selected = ranked_symbols[: self.top_n]
            weights = self._equal_weights(selected)
            return ConstructionResult(weights, set(selected), set(), set(selected), self._turnover(previous_weights, weights), len(selected))

        rank_map = {symbol: index + 1 for index, symbol in enumerate(ranked_symbols)}
        band_holdings = [
            symbol for symbol in ranked_symbols[: self.rank_band]
            if symbol in previous_holdings
        ]
        min_keep = min(len(previous_holdings), int(round(self.top_n * self.min_retention_ratio)))
        max_replace = max(0, int(self.top_n * self.max_replace_ratio))

        retained = band_holdings[: self.top_n]
        if len(retained) < min_keep:
            extra_previous = sorted(
                previous_holdings - set(retained),
                key=lambda symbol: rank_map.get(symbol, 10**9),
            )
            retained.extend(extra_previous[: min_keep - len(retained)])

        retained = retained[: self.top_n]
        candidates = [
            symbol for symbol in ranked_symbols[: self.top_n]
            if symbol not in retained
        ]
        replace_slots = min(max_replace, self.top_n - len(retained), len(candidates))
        selected = retained + candidates[:replace_slots]

        if len(selected) < self.top_n:
            for symbol in ranked_symbols:
                if symbol in selected:
                    continue
                selected.append(symbol)
                if len(selected) >= self.top_n:
                    break

        # 若目标换手超阈值，逐步减少卫星仓数量，优先保留原持仓。
        while True:
            retained_set = set(selected) & previous_holdings
            satellite_set = set(selected) - retained_set
            weights = self._core_satellite_weights(retained_set, satellite_set)
            turnover = self._turnover(previous_weights, weights)
            if turnover <= self.max_turnover or not satellite_set:
                break
            weakest_satellite = max(satellite_set, key=lambda symbol: rank_map.get(symbol, 10**9))
            selected.remove(weakest_satellite)
            replacement = next(
                (
                    symbol for symbol in ranked_symbols
                    if symbol in previous_holdings and symbol not in selected
                ),
                None,
            )
            if replacement is None:
                break
            selected.append(replacement)

        retained_set = set(selected) & previous_holdings
        satellite_set = set(selected) - retained_set
        weights = self._core_satellite_weights(retained_set, satellite_set)
        turnover = self._turnover(previous_weights, weights)
        replacements = len(satellite_set)
        return ConstructionResult(weights, set(selected), retained_set, satellite_set, turnover, replacements)

    def _equal_weights(self, selected: list[str]) -> dict[str, float]:
        weights = {symbol: 0.0 for symbol in self.symbols}
        if not selected:
            return weights
        weight = 1.0 / len(selected)
        for symbol in selected:
            weights[symbol] = weight
        return weights

    def _core_satellite_weights(self, retained: set[str], satellite: set[str]) -> dict[str, float]:
        weights = {symbol: 0.0 for symbol in self.symbols}
        if not retained and not satellite:
            return weights
        if retained and satellite:
            core_each = self.core_weight / len(retained)
            satellite_each = (1 - self.core_weight) / len(satellite)
        elif retained:
            core_each = 1.0 / len(retained)
            satellite_each = 0.0
        else:
            core_each = 0.0
            satellite_each = 1.0 / len(satellite)
        for symbol in retained:
            weights[symbol] = core_each
        for symbol in satellite:
            weights[symbol] = satellite_each
        return weights

    def _turnover(self, previous: dict[str, float], current: dict[str, float]) -> float:
        symbols = set(previous) | set(current)
        return 0.5 * sum(abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols)
