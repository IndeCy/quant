"""代表因子历史持仓的市值分位暴露指标。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def summarize_size_exposure(
    holdings: pd.DataFrame,
    style_correlations: dict[str, float],
    style_groups: dict[str, str],
) -> list[dict[str, Any]]:
    """按策略汇总逐期市值分位，0代表最小、1代表最大。"""
    required = {
        "strategy_id",
        "signal_date",
        "symbol",
        "market_cap_proxy",
        "market_cap_percentile",
    }
    missing = sorted(required.difference(holdings.columns))
    if missing:
        raise ValueError(f"持仓市值归因缺少字段: {missing}")
    rows: list[dict[str, Any]] = []
    for strategy_id, group in holdings.groupby("strategy_id", sort=True):
        covered = group.dropna(
            subset=["market_cap_proxy", "market_cap_percentile"]
        )
        period_medians = covered.groupby("signal_date")[
            "market_cap_percentile"
        ].median()
        percentiles = pd.to_numeric(
            covered["market_cap_percentile"],
            errors="coerce",
        )
        market_caps = pd.to_numeric(
            covered["market_cap_proxy"],
            errors="coerce",
        )
        rows.append(
            {
                "strategy_id": str(strategy_id),
                "style_group": style_groups[str(strategy_id)],
                "style_correlation": float(
                    style_correlations[str(strategy_id)]
                ),
                "holding_records": int(len(group)),
                "covered_records": int(len(covered)),
                "coverage": float(len(covered) / len(group)),
                "signal_periods": int(group["signal_date"].nunique()),
                "unique_symbols": int(group["symbol"].nunique()),
                "median_market_cap_proxy": float(market_caps.median()),
                "median_market_cap_percentile": float(percentiles.median()),
                "median_period_market_cap_percentile": float(
                    period_medians.median()
                ),
                "bottom_quartile_share": float(percentiles.le(0.25).mean()),
                "bottom_half_share": float(percentiles.le(0.50).mean()),
                "top_quartile_share": float(percentiles.ge(0.75).mean()),
            }
        )
    return rows


def compare_style_groups(rows: list[dict[str, Any]]) -> dict[str, float]:
    """比较高低相关代表组，并检验收益风格与实际持仓排序。"""
    frame = pd.DataFrame(rows)
    high = frame[frame["style_group"].eq("HIGH_MIDCAP_CORRELATION")]
    low = frame[frame["style_group"].eq("LOW_MIDCAP_CORRELATION")]
    if len(high) < 2 or len(low) < 2:
        raise ValueError("高低相关代表组各至少需要2个策略")
    high_size = float(
        high["median_period_market_cap_percentile"].median()
    )
    low_size = float(
        low["median_period_market_cap_percentile"].median()
    )
    high_bottom = float(high["bottom_half_share"].median())
    low_bottom = float(low["bottom_half_share"].median())
    return {
        "high_group_median_size_percentile": high_size,
        "low_group_median_size_percentile": low_size,
        "low_minus_high_size_percentile": low_size - high_size,
        "high_group_bottom_half_share": high_bottom,
        "low_group_bottom_half_share": low_bottom,
        "high_minus_low_bottom_half_share": high_bottom - low_bottom,
        "style_corr_vs_size_spearman": float(
            frame["style_correlation"].corr(
                frame["median_period_market_cap_percentile"],
                method="spearman",
            )
        ),
        "minimum_coverage": float(frame["coverage"].min()),
    }


def evaluate_size_exposure_gate(
    comparison: dict[str, float],
) -> dict[str, Any]:
    """应用研究前冻结的持仓级确认门槛。"""
    checks = {
        "all_strategy_coverage_at_least_90pct": (
            comparison["minimum_coverage"] >= 0.90
        ),
        "low_group_size_percentile_lead_at_least_10pct": (
            comparison["low_minus_high_size_percentile"] >= 0.10
        ),
        "high_group_bottom_half_lead_at_least_10pct": (
            comparison["high_minus_low_bottom_half_share"] >= 0.10
        ),
        "style_correlation_orders_smaller_holdings": (
            comparison["style_corr_vs_size_spearman"] <= -0.50
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}
