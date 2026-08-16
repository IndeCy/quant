"""黄金与5年国债等权防守策略的独立多折确认。"""

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
from examples.cross_asset_independent_trend_feasibility_study import (
    EXPERIMENT_ID as FEASIBILITY_ID,
)
from examples.gold_bond_equal_defensive_report import render_report
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


STRATEGY_ID = "gold_bond_equal_defensive_v1"
REPORT_PATH = Path("docs/research/gold-bond-equal-defensive-v1.md")
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
BENCHMARK_SYMBOL = "510300.SH"
ASSET_WEIGHTS = {GOLD_SYMBOL: 0.50, BOND_SYMBOL: 0.50}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="黄金国债等权防守策略 V1",
    category="allocation_strategy",
    hypothesis="黄金与国债固定等权能否作为独立于Quality的低回撤配置策略",
    definition={
        "asset_allocation": ASSET_WEIGHTS,
        "selection_basis": "economic_role_fixed_before_backtest",
        "portfolio": {
            "weighting": "fixed_equal_weight",
            "rebalance": "monthly",
            "cash": 0.0,
        },
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
            "full_annual_return_min": 0.05,
            "full_max_drawdown_floor": -0.20,
            "full_sharpe_min": 0.75,
            "full_calmar_min": 0.30,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.20,
            "median_fold_sharpe_min": 0.50,
            "annual_turnover_max": 1.0,
            "quality_correlation_max": 0.30,
            "positive_years_min": 8,
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
    """登记独立语义与数据指纹后执行固定确认。"""
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
        result, run = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, run)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun]:
    """用统一基金面板重建月频50/50目标和M0成交。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [GOLD_SYMBOL, BOND_SYMBOL, BENCHMARK_SYMBOL],
        start_date="20130101",
        end_date=as_of_date,
    )
    signals = [
        date for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    targets = {
        date.strftime("%Y%m%d"): dict(ASSET_WEIGHTS)
        for date in signals
    }
    benchmark = _benchmark_curve(panel)
    run = run_risk_layer_backtest(
        STRATEGY_ID,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0),
    )
    periods = {
        key: (
            start,
            panel.latest_common_date if end == "LATEST" else end,
        )
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics(
        {STRATEGY_ID: run.result},
        benchmark,
        periods,
    )[STRATEGY_ID]
    annual = build_annual_metrics(run, benchmark, panel.latest_common_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, annual, quality_correlation)
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
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
    return result, run


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    values = panel.adjusted_close[BENCHMARK_SYMBOL].astype(float)
    return values / float(values.iloc[0])


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """执行研究前冻结的收益、风险、稳定性和独立性门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "full_annual_return_at_least_5pct": full["annualized_return"] >= 0.05,
        "full_drawdown_within_20pct": full["max_drawdown"] >= -0.20,
        "full_sharpe_at_least_075": full["sharpe"] >= 0.75,
        "full_calmar_at_least_030": full["calmar"] >= 0.30,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_20pct": (
            min(item["max_drawdown"] for item in folds) >= -0.20
        ),
        "median_fold_sharpe_at_least_050": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.50
        ),
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "quality_correlation_at_most_030": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.30
        ),
        "at_least_eight_positive_years": positive_years >= 8,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        FEASIBILITY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("跨资产统一基金数据门禁尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("跨资产统一基金数据门禁未通过")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
) -> None:
    """保存独立净值和固定持仓，供研究页面直接观察。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    values = run.result.daily_values
    pd.DataFrame(
        {
            "trade_date": values.index,
            "strategy_nav": values / float(values.iloc[0]),
        }
    ).to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "黄金国债等权通过独立多折门槛，可进入前瞻Paper观察"
            if passed
            else "黄金国债等权未通过独立门槛，不创建观察策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "独立确认报告"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值曲线"),
            ExperimentArtifact("latest_holdings", holdings_path, "固定持仓"),
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
