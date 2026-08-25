"""沪深300、黄金和国债三资产固定等权研究。"""

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
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from examples.three_asset_equal_all_weather_report import render_report
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


STRATEGY_ID = "three_asset_equal_all_weather_v1"
REPORT_PATH = Path("docs/research/three-asset-equal-all-weather-v1.md")
EQUITY_SYMBOL = "510300.SH"
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
ASSET_WEIGHTS = {
    EQUITY_SYMBOL: 1.0 / 3.0,
    GOLD_SYMBOL: 1.0 / 3.0,
    BOND_SYMBOL: 1.0 / 3.0,
}
CONTROL_WEIGHTS = {
    "沪深300单资产": {EQUITY_SYMBOL: 1.0},
    "黄金国债50/50": {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5},
}
FEASIBILITY_ID = "cross_asset_independent_trend_data_feasibility_v1"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="三资产固定等权全天候策略 V1",
    category="allocation_strategy",
    hypothesis="固定加入三分之一权益能否在回撤受控时提高黄金国债组合的长期收益",
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
            "full_annual_return_min": 0.07,
            "full_max_drawdown_floor": -0.25,
            "full_sharpe_min": 0.75,
            "full_calmar_min": 0.30,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.50,
            "annual_turnover_max": 1.0,
            "quality_correlation_max": 0.50,
            "positive_years_min": 8,
            "return_uplift_vs_gold_bond_min": 0.005,
            "drawdown_deterioration_vs_gold_bond_max": 0.06,
            "sharpe_shortfall_vs_gold_bond_max": 0.15,
            "drawdown_improvement_vs_equity_min": 0.10,
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
    """登记固定研究指纹后才读取基金大表。"""
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
        result, runs = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs[STRATEGY_ID])
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun]]:
    """在同一基金面板上运行候选和两个固定对照。"""
    symbols = list(ASSET_WEIGHTS)
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        symbols,
        start_date="20130101",
        end_date=as_of_date,
    )
    feasibility = evaluate_data_feasibility(panel, as_of_date)
    if not feasibility["passed"]:
        raise ValueError(f"三资产数据可行性未通过: {feasibility['checks']}")
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    target_sets = {
        STRATEGY_ID: _build_targets(signals, ASSET_WEIGHTS),
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
            targets,
            panel.bars,
            panel.calendar,
            benchmark,
            model,
        )
        for name, targets in target_sets.items()
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
    candidate_metrics = all_metrics[STRATEGY_ID]
    annual = build_annual_metrics(
        runs[STRATEGY_ID],
        benchmark,
        panel.latest_common_date,
    )
    quality_correlation = load_quality_correlation(paths, runs[STRATEGY_ID])
    full_comparison = {
        name: metrics["full"] for name, metrics in all_metrics.items()
    }
    gate = evaluate_gate(
        candidate_metrics,
        annual,
        quality_correlation,
        full_comparison,
    )
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": panel.latest_common_date,
        "data_feasibility": feasibility,
        "period_metrics": candidate_metrics,
        "annual_metrics": annual,
        "full_comparison": full_comparison,
        "quality_return_correlation": quality_correlation,
        "gate": gate,
        "latest_holdings": [
            {
                "signal_date": max(target_sets[STRATEGY_ID]),
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
    return result, runs


def evaluate_data_feasibility(
    panel: FundPortfolioPanel,
    as_of_date: str,
) -> dict[str, Any]:
    """确认三资产足以覆盖固定多折研究，不容忍过旧数据。"""
    latest = pd.Timestamp(panel.latest_common_date)
    as_of = pd.Timestamp(as_of_date)
    coverage = {str(item["symbol"]): item for item in panel.coverage}
    checks = {
        "all_three_assets_present": set(coverage) == set(ASSET_WEIGHTS),
        "all_assets_cover_study_start": all(
            str(item["start_date"]) <= STUDY_START for item in coverage.values()
        ),
        "at_least_2500_common_days": len(panel.calendar) >= 2500,
        "latest_common_data_within_five_calendar_days": (
            0 <= (as_of - latest).days <= 5
        ),
        "common_close_has_no_missing": (
            not panel.adjusted_close[list(ASSET_WEIGHTS)].isna().any().any()
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "coverage": panel.coverage,
        "common_days": len(panel.calendar),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
    full_comparison: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """应用回测前冻结的绝对、稳定性和增量价值门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    gold_bond = full_comparison["黄金国债50/50"]
    equity = full_comparison["沪深300单资产"]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    checks = {
        "full_annual_return_at_least_7pct": full["annualized_return"] >= 0.07,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_075": full["sharpe"] >= 0.75,
        "full_calmar_at_least_030": full["calmar"] >= 0.30,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_050": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.50
        ),
        "annual_turnover_below_1x": full["annual_turnover"] <= 1.0,
        "quality_correlation_at_most_050": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.50
        ),
        "at_least_eight_positive_years": positive_years >= 8,
        "return_uplift_vs_gold_bond_at_least_05pct": (
            full["annualized_return"] - gold_bond["annualized_return"] >= 0.005
        ),
        "drawdown_deterioration_vs_gold_bond_within_6pct": (
            gold_bond["max_drawdown"] - full["max_drawdown"] <= 0.06
        ),
        "sharpe_shortfall_vs_gold_bond_within_015": (
            gold_bond["sharpe"] - full["sharpe"] <= 0.15
        ),
        "drawdown_improvement_vs_equity_at_least_10pct": (
            full["max_drawdown"] - equity["max_drawdown"] >= 0.10
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def _build_targets(
    signals: list[pd.Timestamp],
    weights: dict[str, float],
) -> dict[str, dict[str, float]]:
    """将固定资产配置映射到每个月末信号日。"""
    return {
        date.strftime("%Y%m%d"): dict(weights)
        for date in signals
    }


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    """使用同一面板中的沪深300复权净值作为基准。"""
    values = panel.adjusted_close[EQUITY_SYMBOL].astype(float)
    return values / float(values.iloc[0])


def _require_feasibility_passed(paths: RuntimePaths) -> None:
    """复用已经通过的五资产统一基金数据门禁。"""
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
    """保存失败或成功都可追溯的报告、净值和固定目标。"""
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
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "三资产固定等权通过多折门槛，可进入前瞻Paper确认"
            if passed
            else "三资产固定等权未通过固定门槛，不创建观察策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "三资产研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值曲线"),
            ExperimentArtifact("latest_holdings", holdings_path, "固定目标持仓"),
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
