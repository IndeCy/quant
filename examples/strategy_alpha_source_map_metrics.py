"""多策略收益源地图的相关性和有效独立押注统计。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np
import pandas as pd


def correlation_matrix(
    returns: pd.DataFrame,
    strategy_ids: Sequence[str],
) -> dict[str, dict[str, float]]:
    """输出稳定可序列化的策略日收益相关矩阵。"""
    matrix = returns[list(strategy_ids)].corr()
    return {
        row: {
            column: float(matrix.loc[row, column])
            for column in strategy_ids
        }
        for row in strategy_ids
    }


def downside_correlation_matrix(
    returns: pd.DataFrame,
    strategy_ids: Sequence[str],
    *,
    benchmark_column: str = "benchmark",
) -> dict[str, dict[str, float]]:
    """只在510300下跌日计算相关性，观察压力阶段共振。"""
    downside = returns[returns[benchmark_column].lt(0)]
    if len(downside) < 2:
        raise ValueError("downside correlation requires at least two observations")
    return correlation_matrix(downside, strategy_ids)


def residual_correlation_matrix(
    returns: pd.DataFrame,
    strategy_ids: Sequence[str],
    *,
    benchmark_column: str = "benchmark",
) -> dict[str, dict[str, float]]:
    """逐策略剔除510300线性Beta后计算残差相关性。"""
    benchmark = returns[benchmark_column].astype(float)
    benchmark_variance = float(benchmark.var(ddof=1))
    if benchmark_variance <= 0:
        raise ValueError("benchmark variance must be positive")
    residuals: dict[str, pd.Series] = {}
    for strategy_id in strategy_ids:
        strategy = returns[strategy_id].astype(float)
        beta = float(strategy.cov(benchmark) / benchmark_variance)
        alpha = float(strategy.mean() - beta * benchmark.mean())
        residuals[strategy_id] = strategy - alpha - beta * benchmark
    return correlation_matrix(pd.DataFrame(residuals), strategy_ids)


def effective_bet_count(
    matrix: Mapping[str, Mapping[str, float]],
) -> float:
    """用相关矩阵特征值参与率估算有效独立收益源数量。"""
    labels = list(matrix)
    values = np.array(
        [[float(matrix[row][column]) for column in labels] for row in labels],
        dtype=float,
    )
    eigenvalues = np.linalg.eigvalsh(values)
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    denominator = float(np.square(eigenvalues).sum())
    return (
        float(np.square(eigenvalues.sum()) / denominator)
        if denominator > 0
        else 0.0
    )


def pairwise_risk_map(
    returns: pd.DataFrame,
    strategy_ids: Sequence[str],
    *,
    benchmark_column: str = "benchmark",
) -> list[dict[str, Any]]:
    """计算两两波动分散率和市场下跌日共同亏损比例。"""
    rows: list[dict[str, Any]] = []
    downside_mask = returns[benchmark_column].lt(0)
    for left_index, left in enumerate(strategy_ids):
        for right in strategy_ids[left_index + 1 :]:
            pair = returns[[left, right]].dropna()
            mixed = pair.mean(axis=1)
            mixed_volatility = float(mixed.std(ddof=1))
            weighted_volatility = float(
                0.5 * pair[left].std(ddof=1)
                + 0.5 * pair[right].std(ddof=1)
            )
            stress = returns.loc[downside_mask, [left, right]].dropna()
            rows.append(
                {
                    "left": left,
                    "right": right,
                    "correlation": float(pair[left].corr(pair[right])),
                    "diversification_ratio": (
                        weighted_volatility / mixed_volatility
                        if mixed_volatility > 0
                        else 0.0
                    ),
                    "downside_joint_loss_share": (
                        float((stress[left].lt(0) & stress[right].lt(0)).mean())
                        if len(stress)
                        else 0.0
                    ),
                }
            )
    return rows


def build_correlation_clusters(
    matrix: Mapping[str, Mapping[str, float]],
    *,
    threshold: float = 0.75,
) -> list[list[str]]:
    """把绝对相关性达到阈值的策略归为同一连通收益源。"""
    if not 0 <= threshold <= 1:
        raise ValueError("correlation threshold must be between zero and one")
    remaining = set(matrix)
    clusters: list[list[str]] = []
    while remaining:
        seed = sorted(remaining)[0]
        component = {seed}
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            linked = {
                candidate
                for candidate in remaining
                if abs(float(matrix[current][candidate])) >= threshold
            }
            new_nodes = linked - component
            component.update(new_nodes)
            frontier.extend(sorted(new_nodes))
        remaining -= component
        clusters.append(sorted(component))
    return sorted(clusters, key=lambda cluster: (cluster[0], len(cluster)))


def strategy_metric_summary(nav: pd.Series) -> dict[str, float]:
    """对共同历史净值计算收益、回撤、波动与Sharpe。"""
    values = pd.to_numeric(nav, errors="coerce").dropna()
    if len(values) < 2:
        raise ValueError("strategy metric summary requires two observations")
    normalized = values / float(values.iloc[0])
    returns = normalized.pct_change().dropna()
    years = (len(normalized) - 1) / 252.0
    annualized = float(normalized.iloc[-1] ** (1.0 / years) - 1.0)
    drawdown = normalized / normalized.cummax() - 1.0
    volatility = float(returns.std(ddof=1) * math.sqrt(252))
    return {
        "annualized_return": annualized,
        "max_drawdown": float(drawdown.min()),
        "annualized_volatility": volatility,
        "sharpe": (
            float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
            if returns.std(ddof=1) > 0
            else 0.0
        ),
    }
