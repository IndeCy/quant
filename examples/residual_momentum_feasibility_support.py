"""残差动量数据可行性统计与冻结门禁。"""

from __future__ import annotations

from typing import Any

import pandas as pd


TOP_N = 40
MIN_CANDIDATES = 1_000
MIN_UNIQUE_VALUES = 900
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_INTERMEDIATE_MOMENTUM_CORRELATION = 0.75
MAX_VOLATILITY_CORRELATION = 0.75


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """统计广度、流动性和与既有风格的秩相关。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[
            candidates["signal_date"].astype(str).eq(signal_date)
        ]
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(len(group)),
                "unique_factor_values": int(
                    group["residual_momentum"].nunique()
                ),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": (
                    float(adv.median()) if len(adv) else 0.0
                ),
                "top40_tradable_share": (
                    float(adv.ge(5_000_000.0).mean())
                    if len(adv)
                    else 0.0
                ),
                "spearman_intermediate_momentum": _spearman(
                    group,
                    "factor_score",
                    "intermediate_momentum",
                ),
                "spearman_vol60": _spearman(
                    group,
                    "factor_score",
                    "vol60",
                ),
                "spearman_ret120": _spearman(
                    group,
                    "factor_score",
                    "ret120",
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_date: str,
) -> dict[str, Any]:
    """应用读取任何未来收益前冻结的数据门禁。"""
    if monthly.empty:
        raise ValueError("残差动量没有月末截面")
    if candidates.empty:
        raise ValueError("残差动量没有可投资候选")
    duplicate_rows = int(
        candidates.duplicated(["signal_date", "symbol"]).sum()
    )
    expected = (
        candidates["evaluation_stock_sum"]
        - candidates["market_beta"]
        * candidates["evaluation_market_sum"]
        - candidates["size_beta"]
        * candidates["evaluation_size_sum"]
    )
    identity_error = (
        candidates["residual_momentum"] - expected
    ).abs()
    invalid_rows = int(
        pd.to_numeric(
            candidates["residual_momentum"],
            errors="coerce",
        ).isna().sum()
    )
    visibility_violations = int(
        (
            candidates["signal_index"]
            - candidates["evaluation_max_index"]
        ).lt(20).sum()
        + (
            candidates["signal_index"]
            - candidates["estimation_max_index"]
        ).lt(121).sum()
    )
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(
            MIN_TOP40_MEDIAN_ADV_RMB
        )
        & monthly["top40_tradable_share"].ge(
            MIN_TOP40_TRADABLE_SHARE
        )
    )
    correlations = {
        "intermediate_momentum": float(
            monthly["spearman_intermediate_momentum"].median()
        ),
        "vol60": float(monthly["spearman_vol60"].median()),
        "ret120": float(monthly["spearman_ret120"].median()),
    }
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_intermediate_momentum": (
            abs(correlations["intermediate_momentum"])
            <= MAX_INTERMEDIATE_MOMENTUM_CORRELATION
        ),
        "distinct_from_low_volatility": (
            abs(correlations["vol60"]) <= MAX_VOLATILITY_CORRELATION
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_visibility_violations": visibility_violations == 0,
        "zero_identity_violations": (
            float(identity_error.max() if len(identity_error) else 0.0)
            <= 1e-10
        ),
        "zero_invalid_rows": invalid_rows == 0,
        "regression_identified": (
            float(candidates["determinant"].min()) > 1e-16
        ),
    }
    passed = all(checks.values())
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "qualified_month_share": float(qualified.mean()),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(
            monthly["candidate_count"].median()
        ),
        "candidate_count_latest": int(
            monthly["candidate_count"].iloc[-1]
        ),
        "unique_values_median": float(
            monthly["unique_factor_values"].median()
        ),
        "top40_adv_median_rmb": float(
            monthly["top40_median_adv_rmb"].median()
        ),
        "median_correlations": correlations,
        "minimum_estimation_observations": int(
            candidates["estimation_observations"].min()
        ),
        "minimum_evaluation_observations": int(
            candidates["evaluation_observations"].min()
        ),
        "maximum_identity_error": float(
            identity_error.max() if len(identity_error) else 0.0
        ),
        "duplicate_rows": duplicate_rows,
        "visibility_violations": visibility_violations,
        "invalid_rows": invalid_rows,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_MULTIFOLD_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _spearman(
    frame: pd.DataFrame,
    left: str,
    right: str,
) -> float:
    valid = frame[[left, right]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    if len(valid) < 3:
        return float("nan")
    return float(valid[left].corr(valid[right], method="spearman"))
