"""核心利润纯度研究的股票池、数据门禁和组合诊断。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from factors.core_earnings_purity import score_core_earnings_purity_frame
from portfolio.topn import build_topn_selections


TOP_N = 40
MIN_CANDIDATES = 800
MIN_UNIQUE_VALUES = 500
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95


def build_candidates(source: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """应用标准可投条件、财报新鲜度和正盈利约束。"""
    data = source.copy()
    signal = pd.to_datetime(
        data["signal_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    listed = pd.to_datetime(
        data["list_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    delisted = pd.to_datetime(
        data["delist_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    report_year = pd.to_numeric(
        data["end_date"].astype(str).str[:4],
        errors="coerce",
    )
    numeric = [
        "dtprofit_to_profit",
        "roa",
        "roe",
        "ocf_to_or",
        "salescash_to_or",
        "ret120",
        "amount20",
        "amount",
        "amount_p20",
        "volume",
        "close",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    finite_factor = np.isfinite(data["dtprofit_to_profit"])
    valid = (
        signal.notna()
        & listed.notna()
        & (signal - listed).dt.days.ge(1095)
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~(delisted.notna() & delisted.le(signal))
        & data["end_date"].astype(str).str.endswith("1231")
        & data["f_ann_date"].astype(str).le(data["signal_date"].astype(str))
        & (signal.dt.year - report_year).between(1, 2)
        & data["roa"].gt(0)
        & finite_factor
        & data["amount"].gt(data["amount_p20"])
        & data["volume"].gt(0)
        & data["close"].gt(0)
    )
    accepted = data[valid].copy()
    accepted["adv_rmb"] = accepted["amount20"] * 1000.0
    diagnostics = {
        "visibility_violations": float(
            (
                accepted["f_ann_date"].astype(str)
                > accepted["signal_date"].astype(str)
            ).sum()
        ),
        "duplicate_rows": float(
            accepted.duplicated(["signal_date", "symbol"]).sum()
        ),
        "invalid_factor_rows": float(
            (~np.isfinite(accepted["dtprofit_to_profit"])).sum()
        ),
        "positive_roa_share_before_filter": float(data["roa"].gt(0).mean()),
    }
    return accepted, diagnostics


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月并统计候选广度、唯一值和Top40流动性。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[
            candidates["signal_date"].astype(str).eq(signal_date)
        ]
        scored = score_core_earnings_purity_frame(group)
        selected = scored.head(TOP_N)
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(len(group)),
                "unique_factor_values": int(
                    group["dtprofit_to_profit"].nunique()
                ),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": (
                    float(adv.median()) if len(adv) else 0.0
                ),
                "top40_tradable_share": (
                    float(adv.ge(5_000_000.0).mean()) if len(adv) else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_data_gate(
    monthly: pd.DataFrame,
    diagnostics: dict[str, float],
) -> dict[str, Any]:
    """在收益回测前执行冻结的数据可用性门禁。"""
    if monthly.empty:
        raise ValueError("核心利润纯度没有月末覆盖记录")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "zero_visibility_violations": (
            diagnostics["visibility_violations"] == 0
        ),
        "zero_duplicate_rows": diagnostics["duplicate_rows"] == 0,
        "zero_invalid_factor_rows": (
            diagnostics["invalid_factor_rows"] == 0
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
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
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """将月度因子分数交给通用TopN组合层。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_core_earnings_purity_frame(group)
        scored["signal_date"] = str(signal_date)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(
            factor_score=pd.Series(dtype=float)
        )
        return {}, empty
    scores = pd.concat(frames, ignore_index=True)
    mappings, holdings = build_topn_selections(
        scores,
        "factor_score",
        TOP_N,
    )
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mappings.items()
        if symbols
    }
    return targets, holdings


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """审计因子与既有质量、现金回款和动量维度的关系。"""
    correlations: dict[str, list[float]] = {
        "roa": [],
        "ocf_to_or": [],
        "salescash_to_or": [],
        "ret120": [],
    }
    cutoff_ties: list[int] = []
    top_score_ties: list[int] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_core_earnings_purity_frame(group)
        for column in correlations:
            valid = scored[["factor_score", column]].dropna()
            value = valid["factor_score"].corr(
                valid[column].rank(pct=True),
                method="spearman",
            )
            if pd.notna(value):
                correlations[column].append(float(value))
        selected = holdings[
            holdings["signal_date"].astype(str).eq(str(signal_date))
        ]
        if selected.empty:
            continue
        top_score_ties.append(
            int(
                selected["factor_score"]
                .eq(selected["factor_score"].max())
                .sum()
            )
        )
        cutoff = selected["dtprofit_to_profit"].min()
        cutoff_ties.append(
            int(group["dtprofit_to_profit"].eq(cutoff).sum())
        )
    return {
        "median_spearman_with_roa": _median(correlations["roa"]),
        "median_spearman_with_ocf_to_or": _median(
            correlations["ocf_to_or"]
        ),
        "median_spearman_with_salescash_to_or": _median(
            correlations["salescash_to_or"]
        ),
        "median_spearman_with_ret120": _median(correlations["ret120"]),
        "maximum_cutoff_tie_count": float(max(cutoff_ties, default=0)),
        "maximum_top_score_tie_count": float(
            max(top_score_ties, default=0)
        ),
        "selected_factor_median": float(
            holdings["dtprofit_to_profit"].median()
        ),
        "selected_factor_above_100_share": float(
            holdings["dtprofit_to_profit"].gt(100).mean()
        ),
        "selected_factor_above_200_share": float(
            holdings["dtprofit_to_profit"].gt(200).mean()
        ),
        "selected_roa_median": float(holdings["roa"].median()),
        "selected_roa_below_1_share": float(
            holdings["roa"].lt(1).mean()
        ),
    }


def records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """将Pandas缺失值转换为可持久化的JSON null。"""
    return [
        {
            key: None if pd.isna(value) else value
            for key, value in record.items()
        }
        for record in frame.to_dict("records")
    ]


def _median(values: list[float]) -> float:
    """返回非空序列中位数。"""
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")
