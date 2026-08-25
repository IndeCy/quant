"""Quality Balanced Value V1 的前瞻Paper晋级确认。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.quality_factor_study_support import build_period_metrics
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from runtime.strategy_definition_loader import load_strategy_definition
from runtime.strategy_history_materializer import materialize_strategy_backtest_history
from strategies.quality_value_lowvol_runner import compute_quality_value_lowvol_instance


REPORT_PATH = Path("docs/research/quality-balanced-value-confirmation.md")
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id="quality_balanced_value_forward_paper_v1",
    name="Quality Balanced Value V1 Paper Confirmation",
    category="strategy_confirmation",
    hypothesis="固定Quality80%与E/P、B/P各10%的组合是否具备跨阶段Paper观察价值",
    definition={
        "strategy": {
            "factors": {
                "roe": {"weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
                "roa": {"weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
                "ocf_to_or": {"weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
                "earnings_yield": {"weight": 0.10, "transform": "winsorize_1_99_zscore"},
                "book_yield": {"weight": 0.10, "transform": "winsorize_1_99_zscore"},
            },
            "universe": "quality_cleanup_with_corporate_action_gate",
            "portfolio": {"top_n": 20, "weight": "equal", "rebalance": "monthly"},
            "risk_overlay": {"window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
            "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        },
        "confirmation": {
            "folds": FOLDS,
            "promotion_scope": "forward_paper_only",
            "gate": {
                "full_annual_return": 0.10,
                "full_max_drawdown": -0.30,
                "full_sharpe": 0.65,
                "full_calmar": 0.40,
                "positive_folds": 3,
                "worst_fold_drawdown": -0.30,
                "median_fold_sharpe": 0.35,
            },
        },
        "methodology_version": "confirmation_v1",
    },
)


def run_confirmation(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """确认门槛通过前，不登记可运行策略实例。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        definition = load_strategy_definition("quality_balanced_value_v1")
        computation = compute_quality_value_lowvol_instance(
            definition.to_instance_payload(),
            paths,
            as_of_date,
        )
        latest_date = str(computation.result["trade_date"])
        periods = {
            key: (start, latest_date if end == "LATEST" else end)
            for key, (start, end) in FOLDS.items()
        }
        periods["full"] = ("20150101", latest_date)
        metrics = build_period_metrics(
            {"quality_balanced_value_v1": computation.run.result},
            computation.monitoring_frame.set_index(
                pd.to_datetime(computation.monitoring_frame["trade_date"])
            )["benchmark_nav"],
            periods,
        )["quality_balanced_value_v1"]
        gate = evaluate_confirmation_gate(metrics)
        history = None
        if gate["passed"]:
            history = materialize_strategy_backtest_history(
                paths,
                "quality_balanced_value_v1",
                computation.monitoring_frame,
            )
        output = paths.root / REPORT_PATH
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_report(metrics, gate, latest_date), encoding="utf-8")
        registration = complete_research_attempt(
            attempt,
            metrics={
                "strategy_id": "quality_balanced_value_v1",
                "period_metrics": metrics,
                "gate": gate,
                "deployment_scope": "forward_paper_only",
                "report_path": str(output),
                "history_materialization": (
                    {
                        "row_count": history.row_count,
                        "start_date": history.start_date,
                        "end_date": history.end_date,
                    }
                    if history is not None
                    else None
                ),
            },
            outcome="PASSED" if gate["passed"] else "REJECTED",
            decision_reason=(
                "固定跨阶段门槛通过，允许进入前瞻Paper"
                if gate["passed"]
                else "固定跨阶段门槛未通过，不登记每日策略"
            ),
            artifacts=[ExperimentArtifact("summary", output, "确认报告")],
        )
        return {
            "strategy_id": "quality_balanced_value_v1",
            "period_metrics": metrics,
            "gate": gate,
            "latest_date": latest_date,
            "report_path": str(output),
            "history_materialization": (
                {
                    "row_count": history.row_count,
                    "start_date": history.start_date,
                    "end_date": history.end_date,
                }
                if history is not None
                else None
            ),
            **registration,
        }
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def evaluate_confirmation_gate(
    metrics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """固定Paper门槛不等同于小资金实盘门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
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
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def render_report(
    metrics: dict[str, dict[str, float]],
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} |"
        for period, item in metrics.items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality Balanced Value Paper Confirmation

- 数据截止：{latest_date}
- 本确认使用固定策略，不再比较候选或调整权重。
- 结论只决定是否进入前瞻Paper，不代表具备实盘资格。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 |
|---|---:|---:|---:|---:|---:|
{rows}

## 固定门槛

{checks}

结论：{'允许进入每日Shadow/Paper' if gate['passed'] else '不进入每日调度'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_confirmation(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
