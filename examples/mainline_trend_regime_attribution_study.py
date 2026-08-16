"""主线链动在可见趋势状态下的收益与风险归因研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.mainline_trend_regime_attribution_metrics import (
    attach_regimes,
    build_episode_metrics,
    build_regime_metrics,
    classify_lagged_trend_regime,
    evaluate_regime_candidates,
)
from examples.mainline_trend_regime_attribution_report import render_report
from examples.quality_mainline_diversification_study import (
    CORE_ID,
    CORE_WEIGHT,
    SATELLITE_ID,
    SATELLITE_WEIGHT,
    audit_common_history,
    load_strategy_histories,
    simulate_monthly_allocation,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "mainline_trend_regime_attribution_v1"
REPORT_PATH = Path("docs/research/mainline-trend-regime-attribution-v1.md")
FOLDS = {
    "2020_2021": ("20200615", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="主线链动趋势状态归因 V1",
    category="strategy_attribution",
    hypothesis="主线链动的正收益是否稳定集中于事前可识别的市场趋势状态",
    definition={
        "strategy_id": SATELLITE_ID,
        "comparison_core_id": CORE_ID,
        "comparison_portfolio": {
            "core_weight": CORE_WEIGHT,
            "satellite_weight": SATELLITE_WEIGHT,
            "rebalance": "monthly_next_trading_day",
            "allocation_cost_bps": 10.0,
        },
        "state_source": "market_state_daily:000001.SH",
        "state_definition": {
            "trend": "MA60_ge_MA120_is_UP_else_RISK",
            "momentum": "benchmark_return_20d_gt_0",
            "labels": [
                "UP_POSITIVE",
                "UP_NONPOSITIVE",
                "RISK_POSITIVE",
                "RISK_NONPOSITIVE",
            ],
            "visibility": "close_T_classifies_return_T_plus_1",
        },
        "full_beta_history": "audit_only_not_used",
        "folds": FOLDS,
        "frozen_candidate_gate": {
            "minimum_days": 120,
            "satellite_annualized_return_positive": True,
            "satellite_sharpe_min": 0.5,
            "satellite_beats_core": True,
            "satellite_conditional_drawdown_floor": -0.25,
            "all_folds_positive": True,
            "minimum_five_day_episodes": 5,
            "positive_episode_rate_min": 0.55,
        },
        "diagnostic_only": True,
        "no_strategy_or_risk_change": True,
        "parameters_fixed_before_data_read": True,
        "methodology_version": "lagged_trend_regime_attribution_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先申请研究指纹，再读取完整策略和市场历史。"""
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
        result, daily, metrics, episodes = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, daily, metrics, episodes)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """按严格共同日期构造滞后一日的趋势状态归因。"""
    histories = load_strategy_histories(paths, as_of_date)
    history_audit = audit_common_history(histories)
    if not history_audit["passed"]:
        raise ValueError(f"strategy history audit failed: {history_audit}")
    common = histories[CORE_ID].merge(
        histories[SATELLITE_ID][["trade_date", "nav"]],
        on="trade_date",
        how="inner",
        suffixes=("_core", "_satellite"),
        validate="one_to_one",
    )
    allocation = simulate_monthly_allocation(
        common,
        core_weight=CORE_WEIGHT,
        satellite_weight=SATELLITE_WEIGHT,
        cost_bps=10.0,
    )
    market, full_beta_days = _load_market_states(paths, as_of_date)
    regimes = classify_lagged_trend_regime(market)
    daily = attach_regimes(allocation.daily, regimes)
    audit = _audit_state_history(
        history_audit,
        daily,
        full_beta_days,
    )
    if not audit["passed"]:
        raise ValueError(f"trend regime history audit failed: {audit}")
    periods = {
        name: (start, audit["end_date"] if end == "LATEST" else end)
        for name, (start, end) in FOLDS.items()
    }
    periods["full"] = (audit["start_date"], audit["end_date"])
    metrics = build_regime_metrics(daily, periods)
    episodes = build_episode_metrics(daily)
    candidates = evaluate_regime_candidates(
        metrics,
        episodes,
        list(FOLDS),
    )
    qualified = [
        name for name, item in candidates.items() if item["passed"]
    ]
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(metrics, episodes, candidates, audit),
        encoding="utf-8",
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "as_of_date": as_of_date,
        "history_audit": audit,
        "regime_metrics": metrics.to_dict(orient="records"),
        "candidate_gate": candidates,
        "qualified_regimes": qualified,
        "decision": (
            "CONDITIONAL_RESEARCH_JUSTIFIED"
            if qualified
            else "NO_STABLE_REGIME"
        ),
        "report_path": str(report_path),
        "reused": False,
    }
    return result, daily, metrics, episodes


def _load_market_states(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[pd.DataFrame, int]:
    """读取上证趋势历史，同时审计完整 Beta 状态可用天数。"""
    with sqlite3.connect(paths.monitoring_path) as connection:
        market = pd.read_sql_query(
            """
            SELECT trade_date, benchmark_nav, trend_state
            FROM market_state_daily
            WHERE benchmark_id = '000001.SH' AND trade_date <= ?
            ORDER BY trade_date
            """,
            connection,
            params=[as_of_date],
        )
        full_beta_days = int(
            connection.execute(
                "SELECT COUNT(*) FROM market_beta_daily WHERE trade_date <= ?",
                [as_of_date],
            ).fetchone()[0]
        )
    return market, full_beta_days


def _audit_state_history(
    history_audit: dict[str, Any],
    daily: pd.DataFrame,
    full_beta_days: int,
) -> dict[str, Any]:
    """要求趋势状态覆盖绝大多数共同交易日，禁止历史填充。"""
    common_days = int(history_audit["common_days"])
    classified_days = len(daily)
    coverage = classified_days / common_days if common_days else 0.0
    checks = {
        "strategy_history": bool(history_audit["passed"]),
        "trend_regime_coverage_at_least_97pct": coverage >= 0.97,
        "state_asof_precedes_return_date": bool(
            not daily.empty
            and (
                daily["state_asof_date"].astype(str)
                < daily["trade_date"].astype(str)
            ).all()
        ),
        "at_least_1000_classified_days": classified_days >= 1000,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "start_date": (
            str(daily["trade_date"].min()) if not daily.empty else ""
        ),
        "end_date": (
            str(daily["trade_date"].max()) if not daily.empty else ""
        ),
        "classified_days": classified_days,
        "trend_regime_coverage": coverage,
        "full_beta_days": full_beta_days,
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    daily: pd.DataFrame,
    metrics: pd.DataFrame,
    episodes: pd.DataFrame,
) -> None:
    """持久化成功和失败结论，供研究页去重与回溯。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    daily_path = attempt.output_dir / "daily_regimes.csv"
    metrics_path = attempt.output_dir / "regime_metrics.csv"
    episodes_path = attempt.output_dir / "episode_metrics.csv"
    daily.to_csv(daily_path, index=False)
    metrics.to_csv(metrics_path, index=False)
    episodes.to_csv(episodes_path, index=False)
    qualified = list(result["qualified_regimes"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "CONDITIONAL_RESEARCH_JUSTIFIED"
            if qualified
            else "NO_STABLE_REGIME"
        ),
        decision_reason=(
            f"状态 {','.join(qualified)} 通过冻结门槛，仅允许另开研究"
            if qualified
            else "没有状态通过冻结门槛，停止条件式卫星方向"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "趋势状态归因报告"),
            ExperimentArtifact("daily_regimes", daily_path, "滞后状态日表"),
            ExperimentArtifact("regime_metrics", metrics_path, "状态指标"),
            ExperimentArtifact("episode_metrics", episodes_path, "连续状态段"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定监控事实库和两个策略声明版本。"""
    files = [
        ("monitoring", paths.monitoring_path),
        (
            "core_config",
            paths.config_dir / "strategies" / f"{CORE_ID}.json",
        ),
        (
            "satellite_config",
            paths.config_dir / "strategies" / f"{SATELLITE_ID}.json",
        ),
    ]
    return "|".join(
        f"{name}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for name, path in files
    )


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
