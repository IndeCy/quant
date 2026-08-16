"""标普500、黄金和国债三资产固定等权的多折确认研究。"""

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
from examples.cross_asset_dual_momentum_study import (
    FOLDS,
    STUDY_START,
    build_annual_metrics,
    load_quality_correlation,
)
from examples.global_defensive_equal_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
)
from examples.global_defensive_equal_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from factors.etf_momentum import month_end_signal_dates
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


STRATEGY_ID = "global_defensive_equal_v1"
REPORT_PATH = Path("docs/research/global-defensive-equal-v1.md")
SP500_SYMBOL = "513500.SH"
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
BENCHMARK_SYMBOL = "510300.SH"
ASSET_WEIGHTS = {
    SP500_SYMBOL: 1.0 / 3.0,
    GOLD_SYMBOL: 1.0 / 3.0,
    BOND_SYMBOL: 1.0 / 3.0,
}
CONTROL_WEIGHTS = {
    "标普500单资产": {SP500_SYMBOL: 1.0},
    "黄金国债50/50": {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5},
    "沪深300单资产": {BENCHMARK_SYMBOL: 1.0},
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="全球防守三资产固定等权 V1",
    category="allocation_strategy",
    hypothesis="全球权益、黄金和国债固定等权能否提供独立于A股Quality的低回撤收益",
    definition={
        "asset_allocation": ASSET_WEIGHTS,
        "selection_basis": "economic_role_fixed_before_backtest",
        "portfolio": {
            "weighting": "fixed_equal_weight",
            "rebalance": "monthly",
            "cash": 0.0,
        },
        "controls": CONTROL_WEIGHTS,
        "risk_overlay": "none",
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "folds": FOLDS,
            "full_annual_return_min": 0.06,
            "full_max_drawdown_floor": -0.25,
            "full_sharpe_min": 0.70,
            "full_calmar_min": 0.25,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.45,
            "annual_turnover_max": 1.0,
            "quality_correlation_max": 0.30,
            "positive_years_min": 8,
            "pairwise_asset_correlation_max": 0.50,
            "return_uplift_vs_gold_bond_min": 0.005,
            "drawdown_improvement_vs_sp500_min": 0.08,
            "parameters_fixed_before_backtest": True,
        },
        "feasibility_dependency": FEASIBILITY_ID,
        "promotion_scope": "forward_paper_only",
        "methodology_version": "multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先冻结定义和数据指纹，再运行固定回测。"""
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
        _require_feasibility_passed(paths)
        result, runs, targets = _calculate(paths, as_of_date)
        _complete_attempt(
            attempt,
            result,
            runs[STRATEGY_ID],
            targets,
        )
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    dict[str, RiskLayerRun],
    dict[str, dict[str, float]],
]:
    """同面板运行候选与固定对照，避免数据口径差异。"""
    symbols = [*ASSET_WEIGHTS, BENCHMARK_SYMBOL]
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date="20140101",
        end_date=as_of_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    targets = _build_targets(signals, ASSET_WEIGHTS)
    target_sets = {
        STRATEGY_ID: targets,
        **{
            name: _build_targets(signals, weights)
            for name, weights in CONTROL_WEIGHTS.items()
        },
    }
    benchmark = _benchmark_curve(panel)
    model = ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0)
    runs = {
        name: run_risk_layer_backtest(
            name,
            "FIXED",
            target,
            panel.bars,
            panel.calendar,
            benchmark,
            model,
        )
        for name, target in target_sets.items()
    }
    periods = {
        key: (start, panel.latest_common_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    all_metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(
        runs[STRATEGY_ID],
        benchmark,
        panel.latest_common_date,
    )
    quality_correlation = load_quality_correlation(
        paths,
        runs[STRATEGY_ID],
    )
    asset_correlations = _asset_return_correlations(panel)
    full_comparison = {
        name: metrics["full"]
        for name, metrics in all_metrics.items()
    }
    gate = evaluate_gate(
        all_metrics[STRATEGY_ID],
        annual,
        quality_correlation,
        asset_correlations,
        full_comparison,
    )
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": all_metrics[STRATEGY_ID],
        "annual_metrics": annual,
        "full_comparison": full_comparison,
        "quality_return_correlation": quality_correlation,
        "asset_return_correlations": asset_correlations,
        "gate": gate,
        "latest_holdings": [
            {
                "signal_date": max(targets),
                "symbol": symbol,
                "target_weight": weight,
            }
            for symbol, weight in ASSET_WEIGHTS.items()
        ],
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    output = Path(result["report_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    return result, runs, targets


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
    asset_correlations: dict[str, dict[str, float]],
    full_comparison: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """应用收益、稳定性、独立性和相对价值的预注册门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    pairwise = [
        abs(value)
        for left, row in asset_correlations.items()
        for right, value in row.items()
        if left < right
    ]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    gold_bond = full_comparison["黄金国债50/50"]
    sp500 = full_comparison["标普500单资产"]
    checks = {
        "full_annual_return_at_least_6pct": full["annualized_return"] >= 0.06,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_070": full["sharpe"] >= 0.70,
        "full_calmar_at_least_025": full["calmar"] >= 0.25,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_045": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.45
        ),
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "quality_correlation_at_most_030": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.30
        ),
        "at_least_eight_positive_years": positive_years >= 8,
        "pairwise_asset_correlation_at_most_050": (
            bool(pairwise) and max(pairwise) <= 0.50
        ),
        "return_uplift_vs_gold_bond_at_least_05pct": (
            full["annualized_return"] - gold_bond["annualized_return"] >= 0.005
        ),
        "drawdown_improvement_vs_sp500_at_least_8pct": (
            full["max_drawdown"] - sp500["max_drawdown"] >= 0.08
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
        "maximum_pairwise_asset_correlation": (
            max(pairwise) if pairwise else float("nan")
        ),
    }


def _build_targets(
    signals: list[pd.Timestamp],
    weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    """把固定资产配置映射到每个月末信号日。"""
    return {
        date.strftime("%Y%m%d"): dict(weights)
        for date in signals
    }


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    """使用同面板沪深300复权净值作为基准。"""
    values = panel.adjusted_close[BENCHMARK_SYMBOL].astype(float)
    return values / float(values.iloc[0])


def _asset_return_correlations(
    panel: FundPortfolioPanel,
) -> dict[str, dict[str, float]]:
    """计算三条经济来源的日收益相关性。"""
    matrix = (
        panel.adjusted_close[list(ASSET_WEIGHTS)]
        .pct_change(fill_method=None)
        .corr()
    )
    return {
        str(left): {
            str(right): float(value)
            for right, value in row.items()
        }
        for left, row in matrix.iterrows()
    }


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    """正式回测必须依赖本候选已经通过的数据门禁。"""
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("全球防守三资产数据门禁尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("全球防守三资产数据门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    targets: dict[str, dict[str, float]],
) -> None:
    """保存报告、每日净值和完整月度目标。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    values = run.result.daily_values
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            "trade_date": values.index,
            "strategy_nav": values / float(values.iloc[0]),
        }
    ).to_csv(nav_path, index=False)
    targets_path = attempt.output_dir / "monthly_targets.csv"
    pd.DataFrame(
        [
            {
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for date, weights in targets.items()
            for symbol, weight in weights.items()
        ]
    ).to_csv(targets_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "全球防守三资产通过固定门槛，仅允许进入前瞻Paper确认"
            if passed
            else "全球防守三资产未通过固定门槛，不生成参数变体"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "多折研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值曲线"),
            ExperimentArtifact("monthly_targets", targets_path, "月度目标组合"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金基线、增量和Quality监控数据版本。"""
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
