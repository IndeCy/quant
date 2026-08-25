"""机构席位净买入固定回测的截面构建与晋级门槛。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data.top_inst import TOP_INST_ASOF_TABLE
from factors.top_inst_flow import score_top_inst_flow_frame
from portfolio.topn import build_topn_selections


TOP_N = 20
FOLDS = {
    "2017_2019": ("20170101", "20191231"),
    "2020_2021": ("20200101", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}


def load_backtest_panel(connection: Any) -> pd.DataFrame:
    """应用统一行情口径和标准股票池，保留诊断字段。"""
    return connection.execute(
        f"""
        SELECT
            t.signal_date,
            t.symbol,
            sb.name,
            t.latest_event_date,
            t.unique_seat_events,
            t.event_days,
            t.source_rows,
            t.total_buy,
            t.total_sell,
            t.total_net_buy,
            f.amount20 * 1000.0 AS adv_rmb,
            f.vol60,
            f.ret120
        FROM {TOP_INST_ASOF_TABLE} t
        JOIN features f
          ON t.signal_date = f.trade_date AND t.symbol = f.symbol
        JOIN stock_basic sb ON t.symbol = sb.ts_code
        WHERE f.st_name IS NULL
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
          AND NOT REGEXP_MATCHES(COALESCE(sb.name, ''), 'ST|退')
        ORDER BY t.signal_date, t.symbol
        """
    ).fetchdf()


def build_targets(
    candidates: pd.DataFrame,
    signal_dates: list[str],
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月选择机构净买入强度最高的Top20，候选不足时转现金。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date in signal_dates:
        group = candidates[
            candidates["signal_date"].astype(str).eq(signal_date)
        ]
        scored = score_top_inst_flow_frame(group)
        scored["signal_date"] = signal_date
        counts[signal_date] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    targets: dict[str, dict[str, float]] = {
        signal_date: {} for signal_date in signal_dates
    }
    if not frames:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return targets, empty, _count_summary(counts)
    scores = pd.concat(frames, ignore_index=True)
    mappings, holdings = build_topn_selections(scores, "factor_score", TOP_N)
    targets.update(
        {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in mappings.items()
        }
    )
    return targets, holdings, _count_summary(counts)


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """归因流动性、波动率、动量和市场板块暴露。"""
    correlations = {"adv_rmb": [], "vol60": [], "ret120": []}
    overlaps = {"low_amount": [], "high_vol60": [], "high_momentum": []}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_top_inst_flow_frame(group)
        if len(scored) < TOP_N:
            continue
        rank = scored["factor_score"].rank()
        for field in correlations:
            value = rank.corr(scored[field].rank())
            if pd.notna(value):
                correlations[field].append(float(value))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        comparators = {
            "low_amount": scored.nsmallest(TOP_N, "adv_rmb"),
            "high_vol60": scored.nlargest(TOP_N, "vol60"),
            "high_momentum": scored.nlargest(TOP_N, "ret120"),
        }
        for key, comparator in comparators.items():
            symbols = set(comparator["symbol"].astype(str))
            overlaps[key].append(len(selected & symbols) / TOP_N)
    latest = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ]["symbol"].astype(str)
    return {
        "median_spearman_with_amount20": _median(correlations["adv_rmb"]),
        "median_spearman_with_vol60": _median(correlations["vol60"]),
        "median_spearman_with_ret120": _median(correlations["ret120"]),
        "median_overlap_low_amount": _median(overlaps["low_amount"]),
        "median_overlap_high_vol60": _median(overlaps["high_vol60"]),
        "median_overlap_high_momentum": _median(overlaps["high_momentum"]),
        "selected_flow_ratio_median": float(holdings["net_buy_to_adv"].median()),
        "selected_event_days_median": float(holdings["event_days"].median()),
        "selected_adv_median_rmb": float(holdings["adv_rmb"].median()),
        "latest_bj_share": float(latest.str.endswith(".BJ").mean()),
        "latest_star_share": float(latest.str.match(r"^(688|689)").mean()),
        "latest_chinext_share": float(latest.str.match(r"^(300|301)").mean()),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """执行冻结的跨阶段、风险、成本和独立性门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_30pct": (
            min(item["max_drawdown"] for item in folds) >= -0.30
        ),
        "median_fold_sharpe_at_least_035": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.35
        ),
        "annual_turnover_below_10x": full["annual_turnover"] <= 10.0,
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation) and abs(quality_correlation) <= 0.75
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_folds": sum(item["annualized_return"] > 0 for item in folds),
        "worst_fold_drawdown": min(item["max_drawdown"] for item in folds),
        "median_fold_sharpe": float(
            pd.Series([item["sharpe"] for item in folds]).median()
        ),
    }


def _count_summary(counts: dict[str, int]) -> dict[str, float]:
    values = pd.Series(counts, dtype=float)
    return {
        "min": float(values.min()),
        "median": float(values.median()),
        "latest": float(values.iloc[-1]),
    }


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")
