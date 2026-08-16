"""复核120日低特质波动的窗口稳定性、成本与市场风险来源。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.residual_volatility import materialize_residual_volatility
from examples.earnings_express_acceleration_study import (
    build_annual_metrics,
    load_quality_correlation,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from examples.residual_volatility_robustness_metrics import (
    classify_return_source,
    market_regression_attribution,
    summarize_market_attribution,
)
from examples.residual_volatility_robustness_report import render_report
from examples.residual_volatility_study import (
    STRATEGY_ID,
    TOP_N,
    WINDOW,
    build_diagnostics,
    build_targets,
    load_candidates,
    validate_data_quality,
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


EXPERIMENT_ID = "low_residual_volatility_120d_robustness_v1"
REPORT_PATH = Path(
    "docs/research/low-residual-volatility-120d-robustness-v1.md"
)
SLIPPAGE_SCENARIOS = (5.0, 10.0, 20.0)
NON_OVERLAP_PERIODS: dict[str, tuple[str, str]] = {
    "fold_2015_2017": ("20150101", "20171231"),
    "fold_2018_2020": ("20180101", "20201231"),
    "fold_2021_2023": ("20210101", "20231231"),
    "fold_2024_latest": ("20240101", "latest"),
}
SOURCE_THRESHOLDS = {
    "full_annualized_alpha": 0.02,
    "positive_alpha_period_share": 0.75,
    "full_beta": 0.90,
    "quality_correlation": 0.75,
    "down_capture_must_be_below_up_capture": True,
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="120日低特质波动稳健性与Beta归因",
    category="strategy_robustness",
    hypothesis="锁定期未衰减的低特质波动是否提供跨窗口独立Alpha，而非仅为低Beta暴露",
    definition={
        "control_strategy": STRATEGY_ID,
        "factor": {
            "model": "stock_return=alpha+beta*510300_return+residual",
            "window": WINDOW,
            "direction": "lower_is_better",
        },
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly",
        },
        "execution": "M0_T1_qfq",
        "risk_overlay": "GRID_vol20_45_to_30",
        "slippage_scenarios_bps": SLIPPAGE_SCENARIOS,
        "non_overlap_periods": NON_OVERLAP_PERIODS,
        "source_thresholds": SOURCE_THRESHOLDS,
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
    """登记固定指纹后执行，人工中断也必须关闭运行状态。"""
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
    """只改变执行成本压力，保持因子、股票池和风险层不变。"""
    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=as_of_date,
    )
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        materialize_residual_volatility(
            connection,
            benchmark,
            window=WINDOW,
        )
        signal_dates = load_month_end_signal_dates(connection)
        candidates = load_candidates(connection, signal_dates)
        data_quality = validate_data_quality(candidates)
        if not data_quality["passed"]:
            raise ValueError(f"特质波动数据质量未通过: {data_quality}")
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("低特质波动因子没有产生历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    runs: dict[float, RiskLayerRun] = {}
    for slippage_bps in SLIPPAGE_SCENARIOS:
        runs[slippage_bps] = run_risk_layer_backtest(
            f"{STRATEGY_ID}_{slippage_bps:g}bps",
            "GRID",
            targets,
            bars,
            calendar,
            benchmark,
            ExecutionModel(slippage_bps=slippage_bps),
            vol_window=20,
            vol_threshold=0.45,
            reduced_exposure=0.30,
        )
    base = runs[5.0]
    periods = _resolved_periods(latest_date)
    period_metrics = build_period_metrics(
        {"strategy": base.result},
        benchmark,
        periods,
    )["strategy"]
    cost_stress = {
        f"{bps:g}bps": build_period_metrics(
            {"strategy": run.result},
            benchmark,
            {"full": ("20150101", latest_date)},
        )["strategy"]["full"]
        for bps, run in runs.items()
    }
    annual_metrics = build_annual_metrics(base, benchmark, latest_date)
    market_attribution = {
        period: market_regression_attribution(
            base.result.daily_values.loc[
                pd.Timestamp(start):pd.Timestamp(end)
            ],
            benchmark.loc[pd.Timestamp(start):pd.Timestamp(end)],
        )
        for period, (start, end) in periods.items()
    }
    fold_attribution = {
        period: market_attribution[period]
        for period in NON_OVERLAP_PERIODS
    }
    attribution_summary = summarize_market_attribution(fold_attribution)
    quality_correlation = load_quality_correlation(paths, base)
    source_classification = classify_return_source(
        full_attribution=market_attribution["full"],
        period_summary=attribution_summary,
        quality_correlation=quality_correlation,
    )
    result = {
        "latest_date": latest_date,
        "period_metrics": period_metrics,
        "cost_stress_metrics": cost_stress,
        "annual_metrics": annual_metrics,
        "market_attribution": market_attribution,
        "market_attribution_summary": attribution_summary,
        "source_classification": source_classification,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "data_quality": data_quality,
        "candidate_counts": candidate_counts,
        "decision": "DIAGNOSTIC_COMPLETE_NO_STRATEGY_CHANGE",
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _resolved_periods(latest_date: str) -> dict[str, tuple[str, str]]:
    """把开放式锁定窗口固定到当前数据截止日。"""
    periods = {
        "full": ("20150101", latest_date),
        "without_2015": ("20160101", latest_date),
    }
    periods.update(
        {
            name: (start, latest_date if end == "latest" else min(end, latest_date))
            for name, (start, end) in NON_OVERLAP_PERIODS.items()
        }
    )
    return periods


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """登记收益来源结论，不把诊断结果当成晋级门槛。"""
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
            f"低特质波动来源归因为"
            f"{result['source_classification']['label']}；不改变策略注册状态"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "稳健性与Beta归因报告"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定股票、ETF和增量行情文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
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
