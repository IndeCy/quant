"""经营现金流收益率可行性研究的纯统计与报告函数。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from factors.operating_cashflow_yield import score_operating_cashflow_yield


STUDY_START = "20150101"
TOP_N = 40
MIN_CANDIDATES = 800
MIN_UNIQUE_VALUES = 750
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_STYLE_CORRELATION = 0.80
MAX_ADJUSTMENT_MISSING_SHARE = 0.01


def score_monthly_candidates(source: pd.DataFrame) -> pd.DataFrame:
    """逐月独立计算经营现金流收益率秩。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        scored = score_operating_cashflow_yield(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    if not frames:
        return source.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
    return pd.concat(frames, ignore_index=True)


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """记录每个信号月的覆盖、流动性和风格相关性。"""
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
                    group["operating_cashflow_yield"].nunique()
                ),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": (
                    float(adv.median()) if len(adv) else 0.0
                ),
                "top40_tradable_share": (
                    float(adv.ge(5_000_000).mean()) if len(adv) else 0.0
                ),
                "spearman_roa": _spearman(
                    group,
                    "factor_score",
                    "roa",
                ),
                "spearman_earnings_yield": _spearman(
                    group,
                    "factor_score",
                    "earnings_yield",
                ),
                "spearman_low_vol": _spearman_low(
                    group,
                    "factor_score",
                    "vol60",
                ),
                "spearman_ret120": _spearman(
                    group,
                    "factor_score",
                    "ret120",
                ),
                "spearman_log_adv": _spearman_log_adv(group),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行预注册的数据门禁，不读取未来收益。"""
    if monthly.empty:
        raise ValueError("经营现金流收益率没有月末截面")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    correlations = {
        "roa": float(monthly["spearman_roa"].median()),
        "earnings_yield": float(
            monthly["spearman_earnings_yield"].median()
        ),
        "low_vol": float(monthly["spearman_low_vol"].median()),
        "ret120": float(monthly["spearman_ret120"].median()),
        "log_adv": float(monthly["spearman_log_adv"].median()),
    }
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_roa": abs(correlations["roa"]) <= MAX_STYLE_CORRELATION,
        "distinct_from_earnings_yield": (
            abs(correlations["earnings_yield"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_price_low_volatility": (
            abs(correlations["low_vol"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_momentum": (
            abs(correlations["ret120"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_liquidity_level": (
            abs(correlations["log_adv"]) <= MAX_STYLE_CORRELATION
        ),
        "adjustment_missing_within_limit": (
            diagnostics["adjustment_missing_share"]
            <= MAX_ADJUSTMENT_MISSING_SHARE
        ),
        "zero_visibility_violations": (
            diagnostics["visibility_violations"] == 0
        ),
        "zero_statement_period_mismatches": (
            diagnostics["statement_period_mismatches"] == 0
        ),
        "zero_duplicate_rows": diagnostics["duplicate_rows"] == 0,
        "zero_invalid_rows": diagnostics["invalid_rows"] == 0,
    }
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]["operating_cashflow_yield"]
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
        "latest_distribution": {
            "p01": float(latest.quantile(0.01)),
            "median": float(latest.median()),
            "p99": float(latest.quantile(0.99)),
        },
        "diagnostics": diagnostics,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_PREREGISTERED_MULTIFOLD_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    """生成可复核的数据可行性报告。"""
    correlations = result["median_correlations"]
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 经营现金流收益率数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 唯一因子值中位数：{result['unique_values_median']:.0f}；
  合格月份占比：{result['qualified_month_share']:.2%}。
- Top40 日均成交额中位数：{result['top40_adv_median_rmb'] / 1e6:.1f} 百万元。
- 与 ROA/E/P/低波/120日收益/对数成交额 Spearman 中位数：
  {correlations['roa']:.3f} / {correlations['earnings_yield']:.3f} /
  {correlations['low_vol']:.3f} / {correlations['ret120']:.3f} /
  {correlations['log_adv']:.3f}。
- 最新现金流收益率 P1/中位/P99：{distribution['p01']:.2%} /
  {distribution['median']:.2%} / {distribution['p99']:.2%}。
- 复权缺失/重大公司行为占比：
  {diagnostics['adjustment_missing_share']:.2%} /
  {diagnostics['material_action_share']:.2%}。
- 可见性越界/重复/无效值：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_rows']:.0f} / {diagnostics['invalid_rows']:.0f}。

## 冻结门禁

{checks}

## 结论

决策：`{result['decision']}`。本阶段未读取未来收益或运行回测。
"""


def _spearman(
    frame: pd.DataFrame,
    left: str,
    right: str,
) -> float:
    values = frame[[left, right]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(values[right], method="spearman"))


def _spearman_low(
    frame: pd.DataFrame,
    left: str,
    right: str,
) -> float:
    values = frame[[left, right]].apply(
        pd.to_numeric,
        errors="coerce",
    ).dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(-values[right], method="spearman"))


def _spearman_log_adv(frame: pd.DataFrame) -> float:
    values = frame[["factor_score", "adv_rmb"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    values = values[values["adv_rmb"].gt(0)].dropna()
    if len(values) <= 2:
        return float("nan")
    return float(
        values["factor_score"].corr(
            np.log(values["adv_rmb"]),
            method="spearman",
        )
    )
