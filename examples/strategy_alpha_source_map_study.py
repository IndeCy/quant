"""审计当前正式观察策略究竟包含多少独立Alpha来源。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.residual_volatility_robustness_metrics import (
    market_regression_attribution,
)
from examples.strategy_alpha_source_map_metrics import (
    build_correlation_clusters,
    correlation_matrix,
    downside_correlation_matrix,
    effective_bet_count,
    pairwise_risk_map,
    residual_correlation_matrix,
    strategy_metric_summary,
)
from examples.strategy_alpha_source_map_report import render_report
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "strategy_alpha_source_map_v1"
REPORT_PATH = Path("docs/research/strategy-alpha-source-map-v1.md")
STRATEGIES: dict[str, str] = {
    "quality_overlay": "Quality Alpha",
    "quality_balanced_value_v1": "Balanced Value",
    "quality_defensive_assets_core_scoped_70_15_15_v2": "Defensive Assets",
    "mainline_chain_factor_v1": "Mainline Chain",
}
BENCHMARK_STRATEGY_ID = "quality_overlay"
MIN_COMMON_DAYS = 1_000
CLUSTER_CORRELATION = 0.75
MIN_EFFECTIVE_BETS = 2.50
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="当前观察策略 Alpha 来源地图 V1",
    category="research_governance",
    hypothesis="当前四个正式观察策略是否提供至少2.5个有效且彼此独立的收益源",
    definition={
        "strategies": STRATEGIES,
        "source": "monitoring_strategy_nav_daily_net_of_execution_cost",
        "history": "strict_common_dates_no_fill",
        "benchmark": {
            "id": "510300",
            "source_strategy_id": BENCHMARK_STRATEGY_ID,
        },
        "diagnostics": [
            "daily_return_correlation",
            "benchmark_down_day_correlation",
            "market_beta_residual_correlation",
            "correlation_eigenvalue_effective_bets",
            "pairwise_equal_weight_variance_diversification_only",
        ],
        "cluster_absolute_correlation_threshold": CLUSTER_CORRELATION,
        "minimum_effective_bets": MIN_EFFECTIVE_BETS,
        "minimum_common_days": MIN_COMMON_DAYS,
        "no_new_portfolio_or_weight_selection": True,
        "methodology_version": "v1_preregistered",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记收益源审计指纹后读取统一监控事实表。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """严格对齐共同交易日后计算三类相关性。"""
    histories = _load_histories(paths, as_of_date)
    audit = _audit_histories(histories)
    if not audit["passed"]:
        raise ValueError(f"strategy source map history audit failed: {audit}")
    common = _build_common_frame(histories)
    strategy_labels = list(STRATEGIES.values())
    returns = common[strategy_labels + ["benchmark"]].pct_change().dropna()
    ordinary = correlation_matrix(returns, strategy_labels)
    downside = downside_correlation_matrix(returns, strategy_labels)
    residual = residual_correlation_matrix(returns, strategy_labels)
    effective_bets = {
        "return": effective_bet_count(ordinary),
        "downside": effective_bet_count(downside),
        "residual": effective_bet_count(residual),
    }
    clusters = build_correlation_clusters(
        residual,
        threshold=CLUSTER_CORRELATION,
    )
    summaries = _build_strategy_summaries(
        common,
        strategy_labels,
    )
    pairwise = pairwise_risk_map(returns, strategy_labels)
    concentrated = effective_bets["residual"] < MIN_EFFECTIVE_BETS
    result = {
        "start_date": audit["start_date"],
        "latest_date": audit["end_date"],
        "common_days": audit["common_days"],
        "strategy_summaries": summaries,
        "return_correlation": ordinary,
        "downside_correlation": downside,
        "residual_correlation": residual,
        "effective_bets": effective_bets,
        "clusters": clusters,
        "pairwise_risk_map": pairwise,
        "history_audit": audit,
        "decision": (
            "ALPHA_SOURCE_CONCENTRATION_CONFIRMED"
            if concentrated
            else "ALPHA_SOURCE_DIVERSIFICATION_CONFIRMED"
        ),
        "explanation": (
            "剔除市场Beta后有效押注数仍不足2.5，策略数量高估了真正的收益源数量。"
            if concentrated
            else "剔除市场Beta后仍保留至少2.5个有效押注，收益源具备初步分散性。"
        ),
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(result, strategy_labels),
        encoding="utf-8",
    )
    result["report_path"] = str(report_path)
    return result


def _load_histories(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, pd.DataFrame]:
    """读取四个正式观察策略的净成本曲线。"""
    histories: dict[str, pd.DataFrame] = {}
    with sqlite3.connect(paths.monitoring_path) as connection:
        for strategy_id in STRATEGIES:
            histories[strategy_id] = pd.read_sql_query(
                """
                SELECT trade_date, strategy_id, nav, benchmark_id,
                       benchmark_nav, daily_return
                FROM strategy_nav_daily
                WHERE strategy_id = ? AND trade_date <= ?
                ORDER BY trade_date
                """,
                connection,
                params=[strategy_id, as_of_date],
            )
    return histories


def _audit_histories(
    histories: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """禁止缺策略、重复日期、非正净值和尾部日期错位。"""
    checks: dict[str, bool] = {}
    date_sets: list[set[str]] = []
    end_dates: list[str] = []
    for strategy_id in STRATEGIES:
        frame = histories.get(strategy_id, pd.DataFrame())
        checks[f"{strategy_id}_present"] = not frame.empty
        if frame.empty:
            continue
        checks[f"{strategy_id}_unique_dates"] = not frame["trade_date"].duplicated().any()
        checks[f"{strategy_id}_positive_nav"] = bool(
            frame["nav"].notna().all() and frame["nav"].gt(0).all()
        )
        date_sets.append(set(frame["trade_date"].astype(str)))
        end_dates.append(str(frame["trade_date"].max()))
    common_dates = set.intersection(*date_sets) if len(date_sets) == len(STRATEGIES) else set()
    checks["same_end_date"] = len(set(end_dates)) == 1
    checks["minimum_common_days"] = len(common_dates) >= MIN_COMMON_DAYS
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "common_days": len(common_dates),
        "start_date": min(common_dates) if common_dates else "",
        "end_date": max(common_dates) if common_dates else "",
    }


def _build_common_frame(
    histories: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """按严格内连接生成共同净值面板。"""
    common: pd.DataFrame | None = None
    for strategy_id, label in STRATEGIES.items():
        part = histories[strategy_id][["trade_date", "nav"]].rename(
            columns={"nav": label}
        )
        common = (
            part
            if common is None
            else common.merge(
                part,
                on="trade_date",
                how="inner",
                validate="one_to_one",
            )
        )
    if common is None:
        raise ValueError("strategy histories are empty")
    benchmark = histories[BENCHMARK_STRATEGY_ID][
        ["trade_date", "benchmark_nav"]
    ].rename(columns={"benchmark_nav": "benchmark"})
    common = common.merge(
        benchmark,
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    common = common.sort_values("trade_date").reset_index(drop=True)
    for column in [*STRATEGIES.values(), "benchmark"]:
        common[column] = pd.to_numeric(common[column], errors="raise")
    common.index = pd.to_datetime(common["trade_date"], format="%Y%m%d")
    return common


def _build_strategy_summaries(
    common: pd.DataFrame,
    strategy_labels: list[str],
) -> dict[str, dict[str, float]]:
    """合并净值表现和相对510300的市场回归属性。"""
    summaries: dict[str, dict[str, float]] = {}
    for label in strategy_labels:
        summary = strategy_metric_summary(common[label])
        attribution = market_regression_attribution(
            common[label],
            common["benchmark"],
        )
        summaries[label] = {
            **summary,
            "beta": attribution["beta"],
            "annualized_alpha": attribution["annualized_alpha"],
            "up_capture": attribution["up_capture"],
            "down_capture": attribution["down_capture"],
        }
    return summaries


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """资产化收益源地图，不改变任何策略生命周期。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            f"当前观察策略收益源地图完成：{result['decision']}"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "Alpha来源地图"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定监控事实库和四个策略声明版本。"""
    parts: list[str] = []
    monitoring = paths.monitoring_path
    stat = monitoring.stat()
    parts.append(f"monitoring:{stat.st_size}:{stat.st_mtime_ns}")
    for strategy_id in STRATEGIES:
        path = paths.config_dir / "strategies" / f"{strategy_id}.json"
        stat = path.stat()
        parts.append(f"{strategy_id}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
