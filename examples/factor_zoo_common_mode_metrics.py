"""跨因子年度收益的共同模式、有效广度和风格归因指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def build_annual_metric_matrix(
    runs: list[dict[str, Any]],
    *,
    metric_name: str,
    years: list[int],
) -> tuple[pd.DataFrame, list[str]]:
    """构造固定年份完整面板，缺少任一年数据的实验不参与主分析。"""
    records: list[dict[str, Any]] = []
    for run in runs:
        experiment_id = str(run["experiment_id"])
        annual = run["metrics"]["annual_metrics"]
        for year in years:
            metrics = annual.get(str(year), {})
            value = metrics.get(metric_name)
            if value is not None:
                records.append(
                    {
                        "year": year,
                        "experiment_id": experiment_id,
                        "value": float(value),
                    }
                )
    if not records:
        raise ValueError(f"年度指标为空: {metric_name}")
    matrix = (
        pd.DataFrame(records)
        .pivot(index="year", columns="experiment_id", values="value")
        .reindex(years)
    )
    excluded = sorted(
        column for column in matrix.columns if matrix[column].isna().any()
    )
    complete = matrix.drop(columns=excluded)
    if len(complete) < 5 or complete.shape[1] < 5:
        raise ValueError("完整年度因子面板不足5年或5个实验")
    return complete.astype(float), excluded


def summarize_correlation(matrix: pd.DataFrame) -> dict[str, float]:
    """量化相关矩阵的共同成分和等权有效独立押注数。"""
    correlation = matrix.corr()
    off_diagonal = correlation.where(
        ~np.eye(len(correlation), dtype=bool)
    ).stack()
    eigenvalues = np.clip(
        np.linalg.eigvalsh(correlation.to_numpy(dtype=float)),
        0.0,
        None,
    )
    effective_breadth = float(
        eigenvalues.sum() ** 2 / np.square(eigenvalues).sum()
    )
    standardized = matrix.apply(_zscore_column, axis=0)
    singular_values = np.linalg.svd(
        standardized.to_numpy(dtype=float),
        full_matrices=False,
        compute_uv=False,
    )
    component_power = np.square(singular_values)
    return {
        "average_pairwise_correlation": float(off_diagonal.mean()),
        "median_pairwise_correlation": float(off_diagonal.median()),
        "effective_breadth": effective_breadth,
        "first_component_variance_share": float(
            component_power[0] / component_power.sum()
        ),
    }


def build_style_attribution(
    excess_matrix: pd.DataFrame,
    style_spreads: pd.DataFrame,
) -> dict[str, Any]:
    """解释共同超额是否主要来自中盘或成长风格。"""
    aligned = style_spreads.reindex(excess_matrix.index)
    required = {"csi500_minus_hs300", "chinext_minus_hs300"}
    if not required.issubset(aligned.columns) or aligned.isna().any().any():
        raise ValueError("风格价差与年度因子面板未完整对齐")
    common_excess = excess_matrix.median(axis=1)
    midcap = aligned["csi500_minus_hs300"]
    growth = aligned["chinext_minus_hs300"]
    fit = linear_fit(midcap, common_excess)
    leave_one_out = build_leave_one_year_out(common_excess, midcap)
    strategy_correlations = sorted(
        (
            {
                "experiment_id": str(column),
                "correlation": float(excess_matrix[column].corr(midcap)),
            }
            for column in excess_matrix.columns
        ),
        key=lambda item: item["correlation"],
    )
    residual = residualize_columns(excess_matrix, midcap)
    yearly = [
        {
            "year": int(year),
            "common_excess_return": float(common_excess.loc[year]),
            "csi500_minus_hs300": float(midcap.loc[year]),
            "chinext_minus_hs300": float(growth.loc[year]),
            "positive_excess_share": float(
                excess_matrix.loc[year].gt(0).mean()
            ),
        }
        for year in excess_matrix.index
    ]
    return {
        "common_correlation_to_csi500_spread": float(
            common_excess.corr(midcap)
        ),
        "common_correlation_to_chinext_spread": float(
            common_excess.corr(growth)
        ),
        "csi500_spread_regression": fit,
        "leave_one_year_out": leave_one_out,
        "leave_one_year_out_min_r_squared": float(
            min(item["r_squared"] for item in leave_one_out)
        ),
        "leave_one_year_out_min_correlation": float(
            min(item["correlation"] for item in leave_one_out)
        ),
        "strategy_correlation_ge_070_share": float(
            pd.Series(
                [item["correlation"] for item in strategy_correlations]
            ).ge(0.70).mean()
        ),
        "strategy_correlations": strategy_correlations,
        "residual_correlation_summary": summarize_correlation(residual),
        "yearly_common_mode": yearly,
    }


def build_leave_one_year_out(
    common_excess: pd.Series,
    midcap_spread: pd.Series,
) -> list[dict[str, float]]:
    """逐年剔除，防止单一极端年份主导风格归因。"""
    rows: list[dict[str, float]] = []
    for excluded_year in common_excess.index:
        retained = common_excess.index.difference([excluded_year])
        retained_common = common_excess.loc[retained]
        retained_spread = midcap_spread.loc[retained]
        fit = linear_fit(retained_spread, retained_common)
        rows.append(
            {
                "excluded_year": float(excluded_year),
                "correlation": float(
                    retained_common.corr(retained_spread)
                ),
                "r_squared": float(fit["r_squared"]),
            }
        )
    return rows


def linear_fit(x: pd.Series, y: pd.Series) -> dict[str, float]:
    """使用带截距的一元最小二乘，返回斜率和解释度。"""
    joined = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    design = np.column_stack(
        [np.ones(len(joined)), joined["x"].to_numpy(dtype=float)]
    )
    target = joined["y"].to_numpy(dtype=float)
    intercept, slope = np.linalg.lstsq(
        design,
        target,
        rcond=None,
    )[0]
    predicted = design @ np.array([intercept, slope])
    denominator = float(np.square(target - target.mean()).sum())
    r_squared = (
        1.0 - float(np.square(target - predicted).sum()) / denominator
        if denominator > 0
        else 0.0
    )
    return {
        "intercept": float(intercept),
        "slope": float(slope),
        "r_squared": r_squared,
    }


def residualize_columns(
    matrix: pd.DataFrame,
    explanatory: pd.Series,
) -> pd.DataFrame:
    """逐实验剔除年度中证500相对沪深300价差暴露。"""
    x = explanatory.reindex(matrix.index)
    if x.isna().any():
        raise ValueError("风格序列存在缺失年份")
    residual = pd.DataFrame(index=matrix.index)
    for column in matrix.columns:
        y = matrix[column]
        fit = linear_fit(x, y)
        residual[column] = (
            y - fit["intercept"] - fit["slope"] * x
        )
    return residual


def evaluate_common_mode_gate(
    excess_summary: dict[str, float],
    attribution: dict[str, Any],
) -> dict[str, Any]:
    """应用研究前冻结的共同模式确认门槛。"""
    regression = attribution["csi500_spread_regression"]
    checks = {
        "excess_pc1_share_at_least_50pct": (
            excess_summary["first_component_variance_share"] >= 0.50
        ),
        "common_midcap_r2_at_least_60pct": (
            regression["r_squared"] >= 0.60
        ),
        "leave_one_year_out_r2_at_least_60pct": (
            attribution["leave_one_year_out_min_r_squared"] >= 0.60
        ),
        "strategy_midcap_corr_share_at_least_70pct": (
            attribution["strategy_correlation_ge_070_share"] >= 0.70
        ),
        "effective_breadth_below_5": (
            excess_summary["effective_breadth"] < 5.0
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _zscore_column(series: pd.Series) -> pd.Series:
    standard_deviation = float(series.std(ddof=1))
    if standard_deviation <= 0:
        return pd.Series(0.0, index=series.index)
    return (series - float(series.mean())) / standard_deviation
