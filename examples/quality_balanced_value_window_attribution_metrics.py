"""Quality Balanced Value 低效窗口的因子腿评分与归因工具。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

import pandas as pd

from factors.quality import score_quality_frame, winsorize_series, zscore_series


LEG_WEIGHTS: dict[str, float] = {
    "quality": 0.80,
    "earnings_yield": 0.10,
    "book_yield": 0.10,
}
ATTRIBUTION_VARIANTS: dict[str, tuple[str, ...]] = {
    "quality_only": ("quality",),
    "earnings_yield_only": ("earnings_yield",),
    "book_yield_only": ("book_yield",),
    "quality_earnings": ("quality", "earnings_yield"),
    "quality_book": ("quality", "book_yield"),
    "value_only": ("earnings_yield", "book_yield"),
    "balanced": ("quality", "earnings_yield", "book_yield"),
}
EFFECT_BASELINES: dict[str, tuple[str, str]] = {
    "combined_value_on_quality": ("balanced", "quality_only"),
    "earnings_yield_conditional": ("balanced", "quality_book"),
    "book_yield_conditional": ("balanced", "quality_earnings"),
    "quality_conditional": ("balanced", "value_only"),
}
ATTRIBUTION_METRICS = (
    "annualized_return",
    "max_drawdown",
    "sharpe",
    "calmar",
    "excess_return",
)


def score_factor_leg_subset(
    frame: pd.DataFrame,
    legs: Sequence[str],
) -> pd.DataFrame:
    """按原策略固定权重的相对比例计算指定因子腿得分。"""
    selected_legs = tuple(dict.fromkeys(str(leg) for leg in legs))
    unknown = sorted(set(selected_legs) - set(LEG_WEIGHTS))
    if not selected_legs or unknown:
        raise ValueError(f"unsupported factor legs: {unknown or selected_legs}")

    scored = score_quality_frame(frame)
    market_legs = [
        leg for leg in selected_legs if leg in {"earnings_yield", "book_yield"}
    ]
    missing = [leg for leg in market_legs if leg not in scored.columns]
    if missing:
        raise ValueError(f"factor leg frame missing columns: {missing}")
    scored = scored.dropna(subset=market_legs).copy()
    for leg in market_legs:
        scored[f"{leg}_z"] = zscore_series(
            winsorize_series(scored[leg], lower=0.01, upper=0.99)
        )

    total_weight = sum(LEG_WEIGHTS[leg] for leg in selected_legs)
    scored["factor_score"] = 0.0
    for leg in selected_legs:
        score_column = "quality_score" if leg == "quality" else f"{leg}_z"
        scored["factor_score"] += (
            scored[score_column] * LEG_WEIGHTS[leg] / total_weight
        )
    return scored.sort_values(
        ["factor_score", "symbol"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)


def build_leave_one_out_summary(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    windows: Sequence[str],
) -> dict[str, Any]:
    """计算加入或删除固定因子腿后的逐窗口边际变化。"""
    missing_variants = sorted(set(ATTRIBUTION_VARIANTS) - set(metrics))
    if missing_variants:
        raise ValueError(f"attribution metrics missing variants: {missing_variants}")
    by_window: dict[str, dict[str, dict[str, float]]] = {}
    for window in windows:
        effects: dict[str, dict[str, float]] = {}
        for effect_name, (with_leg, without_leg) in EFFECT_BASELINES.items():
            effects[effect_name] = {
                metric: float(metrics[with_leg][window][metric])
                - float(metrics[without_leg][window][metric])
                for metric in ATTRIBUTION_METRICS
            }
        by_window[str(window)] = effects

    median_effects = {
        effect_name: {
            metric: float(
                median(
                    by_window[str(window)][effect_name][metric]
                    for window in windows
                )
            )
            for metric in ATTRIBUTION_METRICS
        }
        for effect_name in EFFECT_BASELINES
    }
    return {
        "by_window": by_window,
        "median_effects": median_effects,
    }


def diagnose_drag(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    windows: Sequence[str],
    leave_one_out: Mapping[str, Any],
    *,
    sharpe_floor: float = 0.35,
) -> dict[str, Any]:
    """按预注册规则判断低效窗口更接近哪类拖累。"""
    median_sharpes = {
        variant: float(
            median(float(metrics[variant][window]["sharpe"]) for window in windows)
        )
        for variant in ATTRIBUTION_VARIANTS
    }
    value_effect = float(
        leave_one_out["median_effects"]["combined_value_on_quality"]["sharpe"]
    )
    quality_effect = float(
        leave_one_out["median_effects"]["quality_conditional"]["sharpe"]
    )
    standalone = [
        median_sharpes["quality_only"],
        median_sharpes["earnings_yield_only"],
        median_sharpes["book_yield_only"],
    ]
    if all(value < sharpe_floor for value in standalone):
        label = "COMMON_FACTOR_REGIME"
        explanation = "三个独立因子腿的窗口中位Sharpe均低于门槛，拖累并非单一扩展腿造成。"
    elif value_effect <= -0.05:
        label = "VALUE_EXTENSION_DRAG"
        explanation = "加入E/P与B/P后，窗口中位Sharpe相对纯Quality下降至少0.05。"
    elif quality_effect <= -0.05:
        label = "QUALITY_CORE_DRAG"
        explanation = "加入Quality后，窗口中位Sharpe相对纯估值组合下降至少0.05。"
    else:
        label = "MIXED_INTERACTION"
        explanation = "没有单一因子腿形成稳定的大幅负边际，低效来自交互或共同市场环境。"
    return {
        "label": label,
        "explanation": explanation,
        "sharpe_floor": float(sharpe_floor),
        "median_sharpes": median_sharpes,
        "median_value_extension_sharpe_effect": value_effect,
        "median_quality_conditional_sharpe_effect": quality_effect,
    }
