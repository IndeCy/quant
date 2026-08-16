"""解释Quality防守资产为何仍与Quality核心高度同源。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.benchmark_series import load_adjusted_fund_curve
from examples.defensive_sleeve_source_metrics import (
    build_fixed_budget_nav,
    classify_sleeve_dominance,
    variance_risk_contributions,
)
from examples.defensive_sleeve_source_report import render_report
from examples.residual_volatility_robustness_metrics import (
    market_regression_attribution,
)
from examples.strategy_alpha_source_map_metrics import (
    correlation_matrix,
    residual_correlation_matrix,
    strategy_metric_summary,
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


EXPERIMENT_ID = "quality_defensive_sleeve_source_attribution_v1"
SOURCE_EXPERIMENT_ID = "quality_defensive_assets_core_scoped_70_15_15_v2"
REPORT_PATH = Path(
    "docs/research/quality-defensive-sleeve-source-attribution-v1.md"
)
CORE_COLUMN = "quality_balanced_value_core_same_snapshot_v1"
ACTUAL_COLUMN = "quality_defensive_assets_core_scoped_70_15_15_v2"
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
BENCHMARK_SYMBOL = "510300.SH"
WEIGHTS: dict[str, float] = {
    "Quality Core": 0.70,
    "Gold": 0.15,
    "Bond": 0.15,
}
ANALYSIS_LABELS = [
    "Quality Core",
    "Gold",
    "Bond",
    "Defensive Actual",
    "Fixed 70/15/15",
]
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality防守资产袖套来源归因 V1",
    category="strategy_attribution",
    hypothesis="防守策略与核心高度同源是否因为70%核心贡献了超过80%的组合方差",
    definition={
        "source_experiment": SOURCE_EXPERIMENT_ID,
        "source_artifact": "latest_success_daily_nav",
        "fixed_budget": WEIGHTS,
        "fund_assets": {
            "gold": GOLD_SYMBOL,
            "bond": BOND_SYMBOL,
        },
        "benchmark": BENCHMARK_SYMBOL,
        "diagnostics": [
            "standalone_performance",
            "return_correlation",
            "market_beta_residual_correlation",
            "euler_variance_risk_contribution",
        ],
        "dominance_gate": {
            "core_risk_share": 0.80,
            "actual_core_residual_correlation": 0.90,
        },
        "fixed_budget_curve": "daily_rebalanced_no_cost_attribution_only",
        "no_weight_or_strategy_change": True,
        "methodology_version": "v1_preregistered",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先绑定上游回测产物，再执行只读袖套归因。"""
    artifact_path = _latest_source_artifact(paths)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_data_version(paths, artifact_path),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date, artifact_path)
        _complete_attempt(attempt, result)
        return result
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
    artifact_path: Path,
) -> dict[str, Any]:
    """对齐核心回测产物与三条ETF复权曲线。"""
    source = pd.read_csv(artifact_path)
    missing = [
        column
        for column in ["trade_date", CORE_COLUMN, ACTUAL_COLUMN]
        if column not in source.columns
    ]
    if missing:
        raise ValueError(f"defensive sleeve artifact missing columns: {missing}")
    source.index = pd.to_datetime(source["trade_date"])
    curves = {
        "Quality Core": source[CORE_COLUMN].astype(float),
        "Defensive Actual": source[ACTUAL_COLUMN].astype(float),
        "Gold": _load_curve(paths, GOLD_SYMBOL, as_of_date),
        "Bond": _load_curve(paths, BOND_SYMBOL, as_of_date),
        "benchmark": _load_curve(paths, BENCHMARK_SYMBOL, as_of_date),
    }
    aligned = pd.concat(curves, axis=1, join="inner").dropna().sort_index()
    if len(aligned) < 1_000:
        raise ValueError("defensive sleeve attribution requires 1000 common days")
    nav = aligned / aligned.iloc[0]
    underlying_returns = nav[["Quality Core", "Gold", "Bond"]].pct_change().dropna()
    fixed_nav = build_fixed_budget_nav(underlying_returns, WEIGHTS)
    analysis_nav = nav.loc[underlying_returns.index].copy()
    analysis_nav["Fixed 70/15/15"] = fixed_nav
    analysis_returns = analysis_nav[ANALYSIS_LABELS + ["benchmark"]].pct_change().dropna()
    ordinary = correlation_matrix(analysis_returns, ANALYSIS_LABELS)
    residual = residual_correlation_matrix(analysis_returns, ANALYSIS_LABELS)
    summaries = _build_summaries(analysis_nav)
    risk = variance_risk_contributions(underlying_returns, WEIGHTS)
    actual_core_return_correlation = ordinary[
        "Defensive Actual"
    ]["Quality Core"]
    actual_core_residual_correlation = residual[
        "Defensive Actual"
    ]["Quality Core"]
    dominance = classify_sleeve_dominance(
        core_risk_share=risk["risk_contribution_share"]["Quality Core"],
        actual_core_residual_correlation=actual_core_residual_correlation,
    )
    result = {
        "start_date": aligned.index.min().strftime("%Y%m%d"),
        "latest_date": aligned.index.max().strftime("%Y%m%d"),
        "common_days": int(len(aligned)),
        "weights": WEIGHTS,
        "summaries": summaries,
        "return_correlation": ordinary,
        "residual_correlation": residual,
        "risk_contributions": risk,
        "actual_core_return_correlation": actual_core_return_correlation,
        "actual_core_residual_correlation": actual_core_residual_correlation,
        "fixed_actual_return_correlation": ordinary[
            "Fixed 70/15/15"
        ]["Defensive Actual"],
        "dominance": dominance,
        "source_artifact": str(artifact_path),
        "decision": dominance["label"],
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(result, ANALYSIS_LABELS),
        encoding="utf-8",
    )
    result["report_path"] = str(report_path)
    return result


def _load_curve(
    paths: RuntimePaths,
    symbol: str,
    as_of_date: str,
) -> pd.Series:
    """读取统一ETF复权曲线并规范日期索引。"""
    curve = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbol,
        end_date=as_of_date,
    )
    curve.index = pd.to_datetime(curve.index)
    return curve.rename(symbol)


def _build_summaries(
    nav: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """合并每条袖套曲线的净值指标和市场回归。"""
    summaries: dict[str, dict[str, float]] = {}
    benchmark = nav["benchmark"]
    for label in ANALYSIS_LABELS:
        attribution = market_regression_attribution(nav[label], benchmark)
        summaries[label] = {
            **strategy_metric_summary(nav[label]),
            "beta": attribution["beta"],
            "annualized_alpha": attribution["annualized_alpha"],
            "up_capture": attribution["up_capture"],
            "down_capture": attribution["down_capture"],
        }
    return summaries


def _latest_source_artifact(paths: RuntimePaths) -> Path:
    """定位上游最近成功运行的每日袖套净值产物。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        row = connection.execute(
            """
            SELECT output_dir
            FROM experiment_runs
            WHERE experiment_id = ? AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [SOURCE_EXPERIMENT_ID],
        ).fetchone()
    if row is None:
        raise FileNotFoundError("missing successful defensive assets source run")
    path = Path(str(row[0])) / "daily_nav.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing defensive sleeve artifact: {path}")
    return path


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """登记袖套归因，不改变上游策略或权重。"""
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
            f"防守资产袖套归因完成：{result['decision']}"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "袖套来源归因报告"),
        ],
    )


def _data_version(
    paths: RuntimePaths,
    artifact_path: Path,
) -> str:
    """绑定上游回测产物和ETF行情版本。"""
    parts: list[str] = []
    for label, path in [
        ("source_artifact", artifact_path),
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
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
