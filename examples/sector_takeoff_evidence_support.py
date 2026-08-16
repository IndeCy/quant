"""板块起飞前证据研究的纯计算函数。

本模块只构造研究样本和评估统计，不接入策略、调度或交易执行。
所有特征均在信号日收盘后可见，收益标签只用于事后验证。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


STRICT_FORWARD_RETURN = 0.30
STRICT_FORWARD_EXCESS = 0.20
EARLY_MATURITY_RET_60 = 0.50
EARLY_MATURITY_RET_120 = 1.00


def build_monthly_sector_samples(
    daily: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    """以月末为信号日构造点时特征和未来 60 日标签。"""
    required = {
        "ts_code",
        "trade_date",
        "close",
        "amount",
        "turnover_rate",
        "category",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"DC日线缺少字段: {missing}")
    work = daily[daily["category"].eq("概念板块")].copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work = work.sort_values(["ts_code", "trade_date"]).drop_duplicates(
        ["ts_code", "trade_date"],
        keep="last",
    )
    for column in ["close", "amount", "turnover_rate"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["close"])
    grouped = work.groupby("ts_code", sort=False, group_keys=False)
    for window in [20, 60, 120]:
        work[f"ret_{window}"] = grouped["close"].transform(
            lambda values, size=window: values / values.shift(size) - 1.0
        )
    work["future_ret_60"] = grouped["close"].transform(
        lambda values: values.shift(-60) / values - 1.0
    )
    work["amount_ratio_20_120"] = grouped["amount"].transform(
        lambda values: _rolling_ratio(values, 20, 120)
    )
    work["turnover_ratio_20_120"] = grouped["turnover_rate"].transform(
        lambda values: _rolling_ratio(values, 20, 120)
    )
    work["distance_to_high_120"] = grouped["close"].transform(
        lambda values: values / values.rolling(120, min_periods=120).max() - 1.0
    )
    normalized_20 = (1.0 + work["ret_20"]).clip(lower=0.0).pow(3.0) - 1.0
    work["return_acceleration"] = normalized_20 - work["ret_60"]
    work["signal_month"] = work["trade_date"].str[:6]
    samples = work.groupby(["ts_code", "signal_month"], sort=False).tail(1).copy()
    samples = _attach_benchmark(samples, benchmark)
    samples["relative_ret_60"] = samples["ret_60"] - samples["benchmark_ret_60"]
    samples["future_excess_60"] = (
        samples["future_ret_60"] - samples["benchmark_future_ret_60"]
    )
    samples = score_sector_samples(samples)
    samples["strict_takeoff"] = (
        samples["future_ret_60"].ge(STRICT_FORWARD_RETURN)
        & samples["future_excess_60"].ge(STRICT_FORWARD_EXCESS)
    )
    samples["early_eligible"] = (
        samples["ret_60"].le(EARLY_MATURITY_RET_60)
        & samples["ret_120"].le(EARLY_MATURITY_RET_120)
    )
    return samples.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def score_sector_samples(samples: pd.DataFrame) -> pd.DataFrame:
    """按每个信号日的横截面百分位生成冻结的早期证据分。"""
    result = samples.copy()
    features = {
        "relative_ret_60": "strength_pct",
        "return_acceleration": "acceleration_pct",
        "amount_ratio_20_120": "amount_expansion_pct",
        "turnover_ratio_20_120": "turnover_expansion_pct",
        "distance_to_high_120": "near_high_pct",
    }
    for source, target in features.items():
        result[target] = result.groupby("trade_date")[source].rank(
            pct=True,
            method="average",
        )
    raw = 100.0 * (
        0.25 * result["strength_pct"]
        + 0.20 * result["acceleration_pct"]
        + 0.20 * result["amount_expansion_pct"]
        + 0.15 * result["turnover_expansion_pct"]
        + 0.20 * result["near_high_pct"]
    )
    maturity_penalty = (
        10.0 * result["ret_60"].gt(EARLY_MATURITY_RET_60).astype(float)
        + 15.0 * result["ret_120"].gt(EARLY_MATURITY_RET_120).astype(float)
        + 10.0 * result["turnover_ratio_20_120"].gt(3.0).astype(float)
    )
    result["evidence_score"] = (raw - maturity_penalty).clip(0.0, 100.0)
    result["score_decile"] = result.groupby("trade_date")[
        "evidence_score"
    ].transform(_safe_decile)
    return result


def merge_recent_breadth(
    samples: pd.DataFrame,
    breadth_daily: pd.DataFrame,
) -> pd.DataFrame:
    """把可用期较短的板块宽度合并为辅助证据，不改变主分数。"""
    result = samples.copy()
    if breadth_daily.empty:
        result["breadth_20"] = np.nan
        result["breadth_acceleration"] = np.nan
        result["leading_pct_20"] = np.nan
        return result
    required = {"ts_code", "trade_date", "up_num", "down_num", "leading_pct"}
    missing = sorted(required - set(breadth_daily.columns))
    if missing:
        raise ValueError(f"DC宽度数据缺少字段: {missing}")
    breadth = breadth_daily.copy()
    breadth["trade_date"] = breadth["trade_date"].astype(str)
    for column in ["up_num", "down_num", "leading_pct"]:
        breadth[column] = pd.to_numeric(breadth[column], errors="coerce")
    denominator = breadth["up_num"] + breadth["down_num"]
    breadth["breadth"] = breadth["up_num"] / denominator.where(denominator.gt(0))
    breadth = breadth.sort_values(["ts_code", "trade_date"])
    grouped = breadth.groupby("ts_code", sort=False)
    breadth["breadth_20"] = grouped["breadth"].transform(
        lambda values: values.rolling(20, min_periods=10).mean()
    )
    breadth["breadth_60"] = grouped["breadth"].transform(
        lambda values: values.rolling(60, min_periods=20).mean()
    )
    breadth["breadth_acceleration"] = (
        breadth["breadth_20"] - breadth["breadth_60"]
    )
    breadth["leading_pct_20"] = grouped["leading_pct"].transform(
        lambda values: values.rolling(20, min_periods=10).mean()
    )
    columns = [
        "ts_code",
        "trade_date",
        "breadth_20",
        "breadth_acceleration",
        "leading_pct_20",
    ]
    return result.merge(
        breadth[columns].drop_duplicates(["ts_code", "trade_date"], keep="last"),
        on=["ts_code", "trade_date"],
        how="left",
    )


def evaluate_frozen_score(samples: pd.DataFrame) -> dict[str, Any]:
    """评估冻结分数的横截面区分度、年度稳定性和严格起飞命中率。"""
    eligible = samples.dropna(
        subset=[
            "evidence_score",
            "score_decile",
            "future_ret_60",
            "future_excess_60",
        ]
    ).copy()
    eligible = eligible[eligible["trade_date"].between("20210101", "20251231")]
    if eligible.empty:
        raise ValueError("没有可评估的板块月末样本")
    eligible["year"] = eligible["trade_date"].str[:4]
    top = eligible[eligible["score_decile"].eq(10)]
    bottom = eligible[eligible["score_decile"].eq(1)]
    baseline_hit = float(eligible["strict_takeoff"].mean())
    top_hit = float(top["strict_takeoff"].mean())
    bottom_hit = float(bottom["strict_takeoff"].mean())
    deciles = (
        eligible.groupby("score_decile", as_index=False)
        .agg(
            samples=("ts_code", "size"),
            strict_hit_rate=("strict_takeoff", "mean"),
            mean_future_return=("future_ret_60", "mean"),
            median_future_return=("future_ret_60", "median"),
            mean_future_excess=("future_excess_60", "mean"),
        )
        .sort_values("score_decile")
    )
    folds = []
    for year, group in eligible.groupby("year", sort=True):
        year_top = group[group["score_decile"].eq(10)]
        folds.append(
            {
                "year": str(year),
                "samples": int(len(group)),
                "baseline_hit_rate": float(group["strict_takeoff"].mean()),
                "top_decile_samples": int(len(year_top)),
                "top_decile_hit_rate": float(year_top["strict_takeoff"].mean()),
                "top_decile_mean_excess": float(year_top["future_excess_60"].mean()),
            }
        )
    positive_fold_count = sum(item["top_decile_mean_excess"] > 0 for item in folds)
    correlation = float(
        eligible[["evidence_score", "future_excess_60"]]
        .corr(method="spearman")
        .iloc[0, 1]
    )
    checks = {
        "top_hit_lift_ge_1_5": top_hit >= baseline_hit * 1.5,
        "top_mean_excess_positive": float(top["future_excess_60"].mean()) > 0,
        "top_bottom_hit_gap_ge_5pp": top_hit - bottom_hit >= 0.05,
        "positive_years_ge_4": positive_fold_count >= 4,
        "spearman_ge_0_08": correlation >= 0.08,
    }
    return {
        "sample_count": int(len(eligible)),
        "board_count": int(eligible["ts_code"].nunique()),
        "strict_takeoff_count": int(eligible["strict_takeoff"].sum()),
        "baseline_hit_rate": baseline_hit,
        "top_decile_hit_rate": top_hit,
        "bottom_decile_hit_rate": bottom_hit,
        "top_hit_lift": float(top_hit / baseline_hit) if baseline_hit > 0 else 0.0,
        "top_decile_mean_return": float(top["future_ret_60"].mean()),
        "top_decile_mean_excess": float(top["future_excess_60"].mean()),
        "score_future_excess_spearman": correlation,
        "positive_fold_count": int(positive_fold_count),
        "fold_count": int(len(folds)),
        "checks": checks,
        "passed": all(checks.values()),
        "deciles": deciles,
        "folds": pd.DataFrame(folds),
    }


def current_candidate_snapshot(
    samples: pd.DataFrame,
    code_names: pd.DataFrame,
    *,
    top_n: int = 30,
) -> pd.DataFrame:
    """生成截至数据日的早期候选，不把未来标签用于排序。"""
    latest_date = str(samples["trade_date"].max())
    current = samples[samples["trade_date"].eq(latest_date)].copy()
    current = current[
        current["ret_60"].le(EARLY_MATURITY_RET_60)
        & current["ret_120"].le(EARLY_MATURITY_RET_120)
    ]
    names = code_names[["ts_code", "name"]].drop_duplicates(
        "ts_code",
        keep="last",
    )
    current = current.merge(names, on="ts_code", how="left")
    columns = [
        "ts_code",
        "name",
        "trade_date",
        "evidence_score",
        "ret_20",
        "ret_60",
        "ret_120",
        "relative_ret_60",
        "return_acceleration",
        "amount_ratio_20_120",
        "turnover_ratio_20_120",
        "distance_to_high_120",
        "breadth_20",
        "breadth_acceleration",
        "leading_pct_20",
    ]
    return (
        current.sort_values(
            ["evidence_score", "amount_ratio_20_120"],
            ascending=[False, False],
        )
        .head(top_n)[columns]
        .reset_index(drop=True)
    )


def case_study_timeline(
    samples: pd.DataFrame,
    code_names: pd.DataFrame,
    case_codes: list[str],
) -> pd.DataFrame:
    """提取校准案例的严格起飞月和此前证据轨迹。"""
    names = dict(
        code_names[["ts_code", "name"]]
        .drop_duplicates("ts_code", keep="last")
        .itertuples(index=False, name=None)
    )
    rows: list[dict[str, Any]] = []
    for code in case_codes:
        frame = samples[samples["ts_code"].eq(code)].sort_values("trade_date")
        positive = frame[frame["strict_takeoff"]]
        for record in positive.head(3).to_dict("records"):
            rows.append(
                {
                    "ts_code": code,
                    "name": names.get(code, ""),
                    "signal_date": record["trade_date"],
                    "evidence_score": record["evidence_score"],
                    "ret_60": record["ret_60"],
                    "amount_ratio_20_120": record["amount_ratio_20_120"],
                    "turnover_ratio_20_120": record["turnover_ratio_20_120"],
                    "distance_to_high_120": record["distance_to_high_120"],
                    "future_ret_60": record["future_ret_60"],
                    "future_excess_60": record["future_excess_60"],
                }
            )
    return pd.DataFrame(rows)


def _attach_benchmark(
    samples: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> pd.DataFrame:
    required = {"trade_date", "close"}
    missing = sorted(required - set(benchmark.columns))
    if missing:
        raise ValueError(f"基准数据缺少字段: {missing}")
    frame = benchmark[["trade_date", "close"]].copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.sort_values("trade_date").drop_duplicates(
        "trade_date",
        keep="last",
    )
    frame["benchmark_ret_60"] = frame["close"] / frame["close"].shift(60) - 1.0
    frame["benchmark_future_ret_60"] = (
        frame["close"].shift(-60) / frame["close"] - 1.0
    )
    return samples.merge(
        frame[
            [
                "trade_date",
                "benchmark_ret_60",
                "benchmark_future_ret_60",
            ]
        ],
        on="trade_date",
        how="left",
    )


def _rolling_ratio(values: pd.Series, short: int, long: int) -> pd.Series:
    short_mean = values.rolling(short, min_periods=short).mean()
    long_mean = values.rolling(long, min_periods=long).mean()
    return short_mean / long_mean.where(long_mean.ne(0))


def _safe_decile(values: pd.Series) -> pd.Series:
    valid = values.notna().sum()
    if valid < 10:
        return pd.Series(np.nan, index=values.index)
    ranked = values.rank(method="first")
    return pd.qcut(ranked, 10, labels=False, duplicates="drop") + 1
