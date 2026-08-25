"""核心证券组合与固定防守资产袖套的权重合并。"""

from __future__ import annotations

import math

import pandas as pd


def blend_fixed_sleeve_targets(
    core_targets: dict[str, dict[str, float]],
    *,
    core_allocation: float,
    defensive_weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    """按固定预算缩放核心，并在每个核心调仓日加入防守资产。"""
    if not 0 <= core_allocation <= 1:
        raise ValueError("core_allocation must be between 0 and 1")
    if any(weight < 0 for weight in defensive_weights.values()):
        raise ValueError("defensive weights cannot be negative")
    defensive_total = sum(defensive_weights.values())
    if not math.isclose(
        core_allocation + defensive_total,
        1.0,
        abs_tol=1e-12,
    ):
        raise ValueError("core allocation and defensive weights must sum to 1")

    output: dict[str, dict[str, float]] = {}
    for signal_date, weights in sorted(core_targets.items()):
        if not weights:
            continue
        combined = {
            str(symbol): core_allocation * float(weight)
            for symbol, weight in weights.items()
            if weight > 0
        }
        for symbol, weight in defensive_weights.items():
            combined[str(symbol)] = combined.get(str(symbol), 0.0) + float(weight)
        output[str(signal_date)] = combined
    return output


def build_core_scoped_sleeve_targets(
    core_targets: dict[str, dict[str, float]],
    core_exposure: pd.Series,
    *,
    core_allocation: float,
    defensive_weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    """仅在核心调仓或风险暴露变化时生成组合目标。"""
    _validate_allocations(core_allocation, defensive_weights)
    dated_targets = {
        pd.Timestamp(date).normalize(): weights
        for date, weights in core_targets.items()
    }
    output: dict[str, dict[str, float]] = {}
    current_core: dict[str, float] | None = None
    previous_exposure: float | None = None
    for date, exposure_value in core_exposure.sort_index().items():
        normalized_date = pd.Timestamp(date).normalize()
        monthly_rebalance = normalized_date in dated_targets
        if monthly_rebalance:
            current_core = dated_targets[normalized_date]
        exposure = float(exposure_value)
        exposure_changed = (
            previous_exposure is None
            or not math.isclose(exposure, previous_exposure, abs_tol=1e-12)
        )
        if current_core and (monthly_rebalance or exposure_changed):
            combined = {
                str(symbol): core_allocation * exposure * float(weight)
                for symbol, weight in current_core.items()
                if weight > 0
            }
            for symbol, weight in defensive_weights.items():
                combined[str(symbol)] = float(weight)
            output[normalized_date.strftime("%Y%m%d")] = combined
        if current_core is not None:
            previous_exposure = exposure
    return output


def _validate_allocations(
    core_allocation: float,
    defensive_weights: dict[str, float],
) -> None:
    """校验固定预算，允许风险层只降低核心实际暴露。"""
    if not 0 <= core_allocation <= 1:
        raise ValueError("core_allocation must be between 0 and 1")
    if any(weight < 0 for weight in defensive_weights.values()):
        raise ValueError("defensive weights cannot be negative")
    if not math.isclose(
        core_allocation + sum(defensive_weights.values()),
        1.0,
        abs_tol=1e-12,
    ):
        raise ValueError("core allocation and defensive weights must sum to 1")
