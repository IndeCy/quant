"""Quality防守资产三袖套的固定预算风险贡献指标。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


def variance_risk_contributions(
    returns: pd.DataFrame,
    weights: Mapping[str, float],
) -> dict[str, Any]:
    """按固定权重计算组合方差及各袖套欧拉风险贡献。"""
    labels = list(weights)
    if set(labels) != set(returns.columns):
        raise ValueError("risk contribution weights must match return columns")
    weight_vector = np.array([float(weights[label]) for label in labels])
    if not np.isclose(weight_vector.sum(), 1.0):
        raise ValueError("risk contribution weights must sum to one")
    covariance = returns[labels].cov().to_numpy(dtype=float) * 252.0
    portfolio_variance = float(weight_vector @ covariance @ weight_vector)
    if portfolio_variance <= 0:
        raise ValueError("portfolio variance must be positive")
    marginal = covariance @ weight_vector
    components = weight_vector * marginal
    component_shares = components / portfolio_variance
    standalone_volatility = np.sqrt(np.diag(covariance))
    portfolio_volatility = float(np.sqrt(portfolio_variance))
    weighted_standalone = float(weight_vector @ standalone_volatility)
    return {
        "portfolio_annualized_volatility": portfolio_volatility,
        "diversification_ratio": weighted_standalone / portfolio_volatility,
        "component_variance": {
            label: float(component)
            for label, component in zip(labels, components, strict=True)
        },
        "risk_contribution_share": {
            label: float(share)
            for label, share in zip(labels, component_shares, strict=True)
        },
        "standalone_annualized_volatility": {
            label: float(volatility)
            for label, volatility in zip(
                labels,
                standalone_volatility,
                strict=True,
            )
        },
    }


def build_fixed_budget_nav(
    returns: pd.DataFrame,
    weights: Mapping[str, float],
) -> pd.Series:
    """构造无成本每日复位预算曲线，仅用于来源归因。"""
    labels = list(weights)
    weighted = sum(
        returns[label].astype(float) * float(weights[label])
        for label in labels
    )
    return (1.0 + weighted).cumprod().rename("fixed_budget_nav")


def classify_sleeve_dominance(
    *,
    core_risk_share: float,
    actual_core_residual_correlation: float,
    risk_share_threshold: float = 0.80,
    correlation_threshold: float = 0.90,
) -> dict[str, Any]:
    """按预注册阈值判断防守策略是否仍由Quality核心支配。"""
    checks = {
        "core_risk_share_at_least_80pct": (
            core_risk_share >= risk_share_threshold
        ),
        "actual_core_residual_correlation_at_least_090": (
            actual_core_residual_correlation >= correlation_threshold
        ),
    }
    dominated = all(checks.values())
    return {
        "label": (
            "CORE_RISK_DOMINANCE_CONFIRMED"
            if dominated
            else "DEFENSIVE_SLEEVES_MATERIAL_SOURCE_CONFIRMED"
        ),
        "checks": checks,
        "explanation": (
            "黄金和国债降低总波动与回撤，但70% Quality核心仍贡献至少80%的组合方差。"
            if dominated
            else "黄金和国债已形成足够大的独立风险贡献，策略不再由Quality核心单独支配。"
        ),
    }
