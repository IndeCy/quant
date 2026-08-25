"""黄金国债等权防守策略的固定鲁棒性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples.cross_asset_dual_momentum_study import FOLDS, STUDY_START
from examples.gold_bond_equal_defensive_study import (
    BENCHMARK_SYMBOL,
    BOND_SYMBOL,
    GOLD_SYMBOL,
    STRATEGY_ID as BASE_EXPERIMENT_ID,
)
from examples.gold_bond_equal_robustness_report import render_report
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from factors.etf_momentum import month_end_signal_dates
from monitoring.repository import MonitoringRepository
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "gold_bond_equal_defensive_robustness_v1"
BASELINE_ID = "gold_bond_monthly_5bps"
STRESS_10_ID = "gold_bond_monthly_10bps"
STRESS_20_ID = "gold_bond_monthly_20bps"
QUARTERLY_ID = "gold_bond_quarterly_5bps"
GOLD_ONLY_ID = "gold_only_monthly_control"
BOND_ONLY_ID = "bond_only_monthly_control"
REPORT_PATH = Path("docs/research/gold-bond-equal-defensive-robustness-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="黄金国债等权防守策略鲁棒性 V1",
    category="portfolio_robustness",
    hypothesis="黄金国债50/50的通过结果能否在成本、频率和滚动窗口下保持",
    definition={
        "base_strategy": BASE_EXPERIMENT_ID,
        "base_semantics": {
            "weights": {GOLD_SYMBOL: 0.50, BOND_SYMBOL: 0.50},
            "rebalance": "monthly",
            "risk_overlay": "none",
            "execution": "M0_T1_qfq_5bps_no_stamp_tax",
        },
        "stress_tests": {
            "slippage_bps": [10.0, 20.0],
            "rebalance_frequency": "quarterly_diagnostic_only",
            "rolling_window": "3_year_annual_step",
            "single_asset_attribution": [GOLD_SYMBOL, BOND_SYMBOL],
        },
        "frozen_gate": {
            "stress_20_annual_return_min": 0.05,
            "stress_20_drawdown_floor": -0.20,
            "stress_20_sharpe_min": 0.75,
            "quarterly_annual_return_difference_max": 0.01,
            "quarterly_drawdown_deterioration_max": 0.03,
            "quarterly_sharpe_min": 0.70,
            "rolling_positive_share_min": 0.75,
            "rolling_worst_drawdown_floor": -0.20,
            "fold_quality_correlation_max": 0.30,
            "gold_bond_return_correlation_max": 0.40,
            "bond_full_return_positive": True,
        },
        "parameters_fixed_before_stress": True,
        "promotion_scope": "forward_paper_only",
        "methodology_version": "robustness_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记鲁棒性定义与数据版本，再读取基金面板。"""
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
        _require_base_passed(paths)
        result, runs = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun]]:
    """共享同一面板运行固定基线、压力和归因曲线。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [GOLD_SYMBOL, BOND_SYMBOL, BENCHMARK_SYMBOL],
        start_date="20130101",
        end_date=as_of_date,
    )
    monthly = [
        date for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    quarterly = [date for date in monthly if date.month in {3, 6, 9, 12}]
    monthly_targets = _fixed_targets(monthly, {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5})
    quarterly_targets = _fixed_targets(
        quarterly,
        {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5},
    )
    gold_targets = _fixed_targets(monthly, {GOLD_SYMBOL: 1.0})
    bond_targets = _fixed_targets(monthly, {BOND_SYMBOL: 1.0})
    benchmark = _benchmark_curve(panel)
    runs = {
        BASELINE_ID: _run(BASELINE_ID, monthly_targets, panel, benchmark, 5.0),
        STRESS_10_ID: _run(STRESS_10_ID, monthly_targets, panel, benchmark, 10.0),
        STRESS_20_ID: _run(STRESS_20_ID, monthly_targets, panel, benchmark, 20.0),
        QUARTERLY_ID: _run(QUARTERLY_ID, quarterly_targets, panel, benchmark, 5.0),
        GOLD_ONLY_ID: _run(GOLD_ONLY_ID, gold_targets, panel, benchmark, 5.0),
        BOND_ONLY_ID: _run(BOND_ONLY_ID, bond_targets, panel, benchmark, 5.0),
    }
    periods = _periods(panel.latest_common_date)
    metrics = build_period_metrics(
        {key: run.result for key, run in runs.items()},
        benchmark,
        periods,
    )
    rolling = build_rolling_metrics(
        runs[BASELINE_ID],
        benchmark,
        panel.latest_common_date,
    )
    quality_correlations = build_quality_correlations(
        paths,
        runs[BASELINE_ID],
        periods,
    )
    asset_correlation = float(
        runs[GOLD_ONLY_ID].result.daily_values.pct_change().corr(
            runs[BOND_ONLY_ID].result.daily_values.pct_change()
        )
    )
    drawdown = build_drawdown_attribution(runs)
    full_metrics = {
        key: values["full"] for key, values in metrics.items()
    }
    gate = evaluate_gate(
        full_metrics,
        rolling,
        quality_correlations,
        asset_correlation,
    )
    result = {
        "strategy_id": BASE_EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "full_metrics": full_metrics,
        "rolling_metrics": rolling,
        "rolling_positive_share": float(
            pd.Series([
                item["annualized_return"] > 0 for item in rolling.values()
            ]).mean()
        ),
        "quality_correlations": quality_correlations,
        "asset_return_correlation": asset_correlation,
        "drawdown_attribution": drawdown,
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    output = Path(result["report_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    return result, runs


def _fixed_targets(
    dates: list[pd.Timestamp],
    weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    return {date.strftime("%Y%m%d"): dict(weights) for date in dates}


def _run(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    panel: FundPortfolioPanel,
    benchmark: pd.Series,
    slippage_bps: float,
) -> RiskLayerRun:
    return run_risk_layer_backtest(
        strategy_id,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(
            stamp_tax_rate=0.0,
            slippage_bps=slippage_bps,
        ),
    )


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    values = panel.adjusted_close[BENCHMARK_SYMBOL].astype(float)
    return values / float(values.iloc[0])


def _periods(latest_date: str) -> dict[str, tuple[str, str]]:
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, latest_date)
    return periods


def build_rolling_metrics(
    run: RiskLayerRun,
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, float]]:
    """逐年平移三年窗口，最后窗口允许截至当前日。"""
    latest_year = int(latest_date[:4])
    result: dict[str, dict[str, float]] = {}
    for start_year in range(2015, latest_year - 1):
        end_year = start_year + 2
        end_date = min(f"{end_year}1231", latest_date)
        key = f"{start_year}_{end_year}"
        result[key] = metric_summary(
            slice_result(
                run.result,
                f"{start_year}0101",
                end_date,
            ),
            benchmark,
        )
    return result


def build_quality_correlations(
    paths: RuntimePaths,
    run: RiskLayerRun,
    periods: dict[str, tuple[str, str]],
) -> dict[str, float]:
    """逐折检查防守资产与Quality的相关性是否稳定。"""
    quality = MonitoringRepository(paths.monitoring_path).load_strategy_history(
        "quality_balanced_value_v1"
    )
    if quality.empty:
        return {key: float("nan") for key in periods}
    quality_returns = pd.Series(
        quality["daily_return"].astype(float).to_numpy(),
        index=pd.to_datetime(quality["trade_date"], format="%Y%m%d"),
    )
    candidate = run.result.daily_values.pct_change()
    return {
        key: float(
            candidate.loc[pd.Timestamp(start):pd.Timestamp(end)].corr(
                quality_returns.loc[pd.Timestamp(start):pd.Timestamp(end)]
            )
        )
        for key, (start, end) in periods.items()
    }


def build_drawdown_attribution(
    runs: dict[str, RiskLayerRun],
) -> dict[str, Any]:
    """定位组合最大回撤并计算两条资产腿同期表现。"""
    values = runs[BASELINE_ID].result.daily_values.astype(float)
    drawdown = values / values.cummax() - 1.0
    trough = pd.Timestamp(drawdown.idxmin())
    peak = pd.Timestamp(values.loc[:trough].idxmax())

    def period_return(strategy_id: str) -> float:
        series = runs[strategy_id].result.daily_values.loc[peak:trough]
        return float(series.iloc[-1] / series.iloc[0] - 1.0)

    return {
        "peak_date": peak.strftime("%Y%m%d"),
        "trough_date": trough.strftime("%Y%m%d"),
        "portfolio_return": period_return(BASELINE_ID),
        "gold_return": period_return(GOLD_ONLY_ID),
        "bond_return": period_return(BOND_ONLY_ID),
    }


def evaluate_gate(
    full_metrics: dict[str, dict[str, float]],
    rolling: dict[str, dict[str, float]],
    quality_correlations: dict[str, float],
    asset_correlation: float,
) -> dict[str, Any]:
    """执行固定压力、稳定性和收益来源门槛。"""
    baseline = full_metrics[BASELINE_ID]
    stress = full_metrics[STRESS_20_ID]
    quarterly = full_metrics[QUARTERLY_ID]
    rolling_positive = float(
        pd.Series([
            item["annualized_return"] > 0 for item in rolling.values()
        ]).mean()
    )
    checks = {
        "stress20_annual_return_at_least_5pct": (
            stress["annualized_return"] >= 0.05
        ),
        "stress20_drawdown_within_20pct": stress["max_drawdown"] >= -0.20,
        "stress20_sharpe_at_least_075": stress["sharpe"] >= 0.75,
        "quarterly_return_difference_within_1pct": (
            abs(quarterly["annualized_return"] - baseline["annualized_return"])
            <= 0.01
        ),
        "quarterly_drawdown_deterioration_within_3pct": (
            quarterly["max_drawdown"] - baseline["max_drawdown"] >= -0.03
        ),
        "quarterly_sharpe_at_least_070": quarterly["sharpe"] >= 0.70,
        "rolling_positive_share_at_least_75pct": rolling_positive >= 0.75,
        "rolling_worst_drawdown_within_20pct": (
            min(item["max_drawdown"] for item in rolling.values()) >= -0.20
        ),
        "all_fold_quality_correlations_within_030": all(
            pd.notna(value) and abs(value) <= 0.30
            for value in quality_correlations.values()
        ),
        "gold_bond_correlation_within_040": (
            pd.notna(asset_correlation) and abs(asset_correlation) <= 0.40
        ),
        "bond_full_return_positive": (
            full_metrics[BOND_ONLY_ID]["annualized_return"] > 0
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _require_base_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        BASE_EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("黄金国债等权基础实验尚未成功完成")
    if latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("黄金国债等权基础研究门槛未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
) -> None:
    """保存压力场景净值与鲁棒性结论。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "stress_nav.csv"
    pd.DataFrame({
        key: run.result.daily_values / float(run.result.daily_values.iloc[0])
        for key, run in runs.items()
    }).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "成本、频率、滚动窗口和相关性鲁棒，具备前瞻Paper资格"
            if passed
            else "至少一项固定鲁棒性门槛失败，暂不进入Paper"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "鲁棒性报告"),
            ExperimentArtifact("stress_nav", nav_path, "压力与单腿净值"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
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
