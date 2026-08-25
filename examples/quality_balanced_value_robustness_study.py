"""Quality Balanced Value V1 的首年依赖、窗口和成本稳健性审计。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.quality_balanced_value_robustness_metrics import (
    evaluate_robustness_gate,
    positive_year_concentration,
    summarize_window_stability,
)
from examples.quality_balanced_value_robustness_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from runtime.strategy_definition_loader import load_strategy_definition
from strategies.quality_value_lowvol_runner import (
    QualityValueLowVolComputation,
    compute_quality_value_lowvol_instance,
)


EXPERIMENT_ID = "quality_balanced_value_robustness_v1"
REPORT_PATH = Path(
    "docs/research/quality-balanced-value-robustness-v1.md"
)
SLIPPAGE_SCENARIOS = (5.0, 10.0, 20.0)
COMPLETE_THREE_YEAR_WINDOWS = {
    f"{start}_{start + 2}": (
        f"{start}0101",
        f"{start + 2}1231",
    )
    for start in range(2015, 2024)
}
ANNUAL_PERIODS = {
    str(year): (f"{year}0101", f"{year}1231")
    for year in range(2015, 2027)
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality Balanced Value V1 稳健性审计",
    category="strategy_robustness",
    hypothesis="固定策略的历史表现是否不依赖2015且能承受完整三年窗口和20bps滑点压力",
    definition={
        "strategy_id": "quality_balanced_value_v1",
        "strategy_contract": {
            "factors": {
                "roe": 0.8 / 3,
                "roa": 0.8 / 3,
                "ocf_to_or": 0.8 / 3,
                "earnings_yield": 0.10,
                "book_yield": 0.10,
            },
            "top_n": 20,
            "rebalance": "monthly",
            "risk_overlay": "vol_20_45_to_30",
            "execution": "M0_T1_qfq",
        },
        "diagnostics": {
            "without_first_year": ("20160101", "latest"),
            "complete_three_year_windows": COMPLETE_THREE_YEAR_WINDOWS,
            "annual_periods": ANNUAL_PERIODS,
            "slippage_bps": SLIPPAGE_SCENARIOS,
            "positive_return_concentration": "calendar_year_log_returns",
        },
        "frozen_gate": {
            "full_return": 0.10,
            "full_drawdown": -0.30,
            "full_sharpe": 0.65,
            "without_2015_return": 0.08,
            "without_2015_drawdown": -0.30,
            "without_2015_sharpe": 0.55,
            "three_year_positive_share": 0.75,
            "three_year_positive_excess_share": 0.50,
            "three_year_median_sharpe": 0.35,
            "three_year_worst_drawdown": -0.35,
            "cost_20bps_return": 0.10,
            "cost_20bps_drawdown": -0.30,
            "cost_20bps_sharpe": 0.60,
            "top_positive_year_contribution": 0.40,
            "positive_years": 7,
        },
        "decision": "diagnostic_only_no_strategy_change",
        "methodology_version": "v1_preregistered",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在计算历史路径前登记固定稳健性定义。"""
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
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, Any]:
    """运行固定滑点场景并生成不参与选参的诊断指标。"""
    definition = load_strategy_definition("quality_balanced_value_v1")
    base_instance = definition.to_instance_payload()
    computations = {
        bps: _compute_with_slippage(
            base_instance,
            paths,
            as_of_date,
            bps,
        )
        for bps in SLIPPAGE_SCENARIOS
    }
    base = computations[5.0]
    latest_date = str(base.result["trade_date"])
    benchmark = _benchmark_series(base)
    period_metrics = _period_metrics(
        base,
        benchmark,
        {
            "full": ("20150101", latest_date),
            "without_2015": ("20160101", latest_date),
            "2024_latest": ("20240101", latest_date),
        },
    )
    three_year_metrics = _period_metrics(
        base,
        benchmark,
        COMPLETE_THREE_YEAR_WINDOWS,
    )
    annual_periods = {
        year: (start, min(end, latest_date))
        for year, (start, end) in ANNUAL_PERIODS.items()
        if start <= latest_date
    }
    annual_metrics = _period_metrics(
        base,
        benchmark,
        annual_periods,
    )
    cost_stress_metrics = {
        f"{bps:g}bps": _period_metrics(
            computation,
            _benchmark_series(computation),
            {"full": ("20150101", latest_date)},
        )["full"]
        for bps, computation in computations.items()
    }
    window_summary = summarize_window_stability(three_year_metrics)
    concentration = positive_year_concentration(annual_metrics)
    gate = evaluate_robustness_gate(
        full_metrics=period_metrics["full"],
        without_2015_metrics=period_metrics["without_2015"],
        cost_20bps_metrics=cost_stress_metrics["20bps"],
        window_summary=window_summary,
        concentration=concentration,
    )
    result = {
        "latest_date": latest_date,
        "period_metrics": period_metrics,
        "three_year_metrics": three_year_metrics,
        "annual_metrics": annual_metrics,
        "cost_stress_metrics": cost_stress_metrics,
        "window_summary": window_summary,
        "concentration": concentration,
        "gate": gate,
        "decision": (
            "ROBUSTNESS_CONFIRMED_KEEP_FORWARD_PAPER"
            if gate["passed"]
            else "ROBUSTNESS_NOT_CONFIRMED_KEEP_FORWARD_PAPER_ONLY"
        ),
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _compute_with_slippage(
    base_instance: dict[str, Any],
    paths: RuntimePaths,
    as_of_date: str,
    slippage_bps: float,
) -> QualityValueLowVolComputation:
    """只改变执行压力参数，不改变策略信号或组合权重。"""
    instance = deepcopy(base_instance)
    config = dict(instance.get("config") or {})
    config["execution_slippage_bps"] = float(slippage_bps)
    instance["config"] = config
    return compute_quality_value_lowvol_instance(
        instance,
        paths,
        as_of_date,
    )


def _period_metrics(
    computation: QualityValueLowVolComputation,
    benchmark: pd.Series,
    periods: dict[str, tuple[str, str]],
) -> dict[str, dict[str, float]]:
    """复用统一研究指标口径。"""
    return build_period_metrics(
        {"strategy": computation.run.result},
        benchmark,
        periods,
    )["strategy"]


def _benchmark_series(
    computation: QualityValueLowVolComputation,
) -> pd.Series:
    """从同一次计算提取基准净值并恢复交易日索引。"""
    frame = computation.monitoring_frame.copy()
    index = pd.to_datetime(frame["trade_date"])
    return pd.Series(
        frame["benchmark_nav"].astype(float).to_numpy(),
        index=index,
        name="510300",
    )


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存结构化指标和报告，不改变策略注册状态。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if result["gate"]["passed"] else "REJECTED",
        decision_reason=(
            "首年依赖、三年窗口和20bps成本压力均通过"
            if result["gate"]["passed"]
            else "至少一个预注册稳健性门槛未通过，继续只做前瞻Paper"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "稳健性审计报告"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定策略计算依赖的数据文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
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
