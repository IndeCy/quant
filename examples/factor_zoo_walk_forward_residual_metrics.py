"""因子年度超额的走步中盘风格残差指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


VALIDATION_TRAIN_YEARS = list(range(2015, 2019))
VALIDATION_YEARS = list(range(2019, 2022))
LOCKED_TRAIN_YEARS = list(range(2015, 2022))
LOCKED_YEARS = list(range(2022, 2027))


def evaluate_residual_candidates(
    excess_matrix: pd.DataFrame,
    midcap_spread: pd.Series,
) -> list[dict[str, Any]]:
    """逐策略按固定走步窗口估计风格暴露并评价样本外残差。"""
    required_years = sorted(
        set(
            VALIDATION_TRAIN_YEARS
            + VALIDATION_YEARS
            + LOCKED_YEARS
        )
    )
    if not set(required_years).issubset(excess_matrix.index):
        raise ValueError("因子年度超额缺少固定走步年份")
    if not set(required_years).issubset(midcap_spread.index):
        raise ValueError("中盘风格价差缺少固定走步年份")
    rows = [
        evaluate_single_candidate(
            str(column),
            excess_matrix[column],
            midcap_spread,
        )
        for column in excess_matrix.columns
    ]
    return sorted(
        rows,
        key=lambda item: (
            item["gate_pass_count"],
            item["locked_residual_information_ratio"],
            item["locked_mean_residual"],
        ),
        reverse=True,
    )


def evaluate_single_candidate(
    experiment_id: str,
    annual_excess: pd.Series,
    midcap_spread: pd.Series,
) -> dict[str, Any]:
    """训练期只估计斜率，截距作为候选可能保留的独立Alpha。"""
    validation_beta = estimate_style_beta(
        annual_excess,
        midcap_spread,
        VALIDATION_TRAIN_YEARS,
    )
    locked_beta = estimate_style_beta(
        annual_excess,
        midcap_spread,
        LOCKED_TRAIN_YEARS,
    )
    validation_residual = neutralized_residual(
        annual_excess,
        midcap_spread,
        VALIDATION_YEARS,
        validation_beta,
    )
    locked_residual = neutralized_residual(
        annual_excess,
        midcap_spread,
        LOCKED_YEARS,
        locked_beta,
    )
    locked_standard_deviation = float(locked_residual.std(ddof=1))
    locked_information_ratio = (
        float(locked_residual.mean() / locked_standard_deviation)
        if locked_standard_deviation > 0
        else 0.0
    )
    checks = {
        "validation_mean_residual_positive": (
            float(validation_residual.mean()) > 0
        ),
        "locked_mean_residual_positive": (
            float(locked_residual.mean()) > 0
        ),
        "locked_positive_year_share_at_least_60pct": (
            float(locked_residual.gt(0).mean()) >= 0.60
        ),
        "locked_residual_information_ratio_at_least_025": (
            locked_information_ratio >= 0.25
        ),
        "locked_worst_residual_within_20pct": (
            float(locked_residual.min()) >= -0.20
        ),
    }
    return {
        "experiment_id": experiment_id,
        "validation_beta": validation_beta,
        "locked_beta": locked_beta,
        "validation_mean_residual": float(validation_residual.mean()),
        "validation_positive_year_share": float(
            validation_residual.gt(0).mean()
        ),
        "locked_mean_residual": float(locked_residual.mean()),
        "locked_positive_year_share": float(
            locked_residual.gt(0).mean()
        ),
        "locked_worst_residual": float(locked_residual.min()),
        "locked_residual_information_ratio": locked_information_ratio,
        "gate_pass_count": int(sum(checks.values())),
        "gate_passed": bool(all(checks.values())),
        "failed_checks": [
            name for name, passed in checks.items() if not passed
        ],
        "validation_residuals": _dated_values(validation_residual),
        "locked_residuals": _dated_values(locked_residual),
    }


def estimate_style_beta(
    annual_excess: pd.Series,
    midcap_spread: pd.Series,
    train_years: list[int],
) -> float:
    """只用指定训练年份估计带截距OLS的风格斜率。"""
    joined = pd.concat(
        [
            annual_excess.reindex(train_years).rename("excess"),
            midcap_spread.reindex(train_years).rename("style"),
        ],
        axis=1,
    ).dropna()
    if len(joined) != len(train_years) or len(joined) < 3:
        raise ValueError("风格Beta训练年份不完整")
    design = np.column_stack(
        [np.ones(len(joined)), joined["style"].to_numpy(dtype=float)]
    )
    _, beta = np.linalg.lstsq(
        design,
        joined["excess"].to_numpy(dtype=float),
        rcond=None,
    )[0]
    return float(beta)


def neutralized_residual(
    annual_excess: pd.Series,
    midcap_spread: pd.Series,
    years: list[int],
    beta: float,
) -> pd.Series:
    """仅扣除训练期风格斜率，保留未解释截距作为候选Alpha。"""
    excess = annual_excess.reindex(years)
    style = midcap_spread.reindex(years)
    if excess.isna().any() or style.isna().any():
        raise ValueError("样本外残差年份存在缺失")
    return excess - beta * style


def summarize_candidate_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    """汇总旧因子动物园在样本外残差门槛下的存活情况。"""
    frame = pd.DataFrame(rows)
    return {
        "candidate_count": float(len(frame)),
        "gate_pass_count": float(frame["gate_passed"].sum()),
        "validation_positive_count": float(
            frame["validation_mean_residual"].gt(0).sum()
        ),
        "locked_positive_count": float(
            frame["locked_mean_residual"].gt(0).sum()
        ),
        "both_period_positive_count": float(
            (
                frame["validation_mean_residual"].gt(0)
                & frame["locked_mean_residual"].gt(0)
            ).sum()
        ),
        "median_validation_residual": float(
            frame["validation_mean_residual"].median()
        ),
        "median_locked_residual": float(
            frame["locked_mean_residual"].median()
        ),
        "median_locked_information_ratio": float(
            frame["locked_residual_information_ratio"].median()
        ),
    }


def _dated_values(series: pd.Series) -> dict[str, float]:
    return {
        str(int(year)): float(value)
        for year, value in series.items()
    }
