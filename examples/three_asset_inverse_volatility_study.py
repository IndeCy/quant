"""沪深300、黄金和国债三资产逆波动风险预算研究。"""

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
from examples.three_asset_inverse_volatility_report import render_report
from factors.etf_momentum import month_end_signal_dates
from portfolio.inverse_volatility import build_inverse_volatility_targets
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


STRATEGY_ID = "three_asset_inverse_volatility_v1"
REPORT_PATH = Path("docs/research/three-asset-inverse-volatility-v1.md")
EQUITY_SYMBOL = "510300.SH"
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
ASSETS = [EQUITY_SYMBOL, GOLD_SYMBOL, BOND_SYMBOL]
LOOKBACK_DAYS = 60
GOLD_BOND_WEIGHTS = {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5}
FEASIBILITY_ID = "cross_asset_independent_trend_data_feasibility_v1"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="三资产逆波动风险预算 V1",
    category="allocation_strategy",
    hypothesis="三资产等风险分配能否以有限收益代价显著改善黄金国债等权的尾部风险",
    definition={
        "asset_pool": ASSETS,
        "portfolio": {
            "weighting": "inverse_annualized_volatility",
            "lookback_trading_days": LOOKBACK_DAYS,
            "rebalance": "monthly",
            "leverage": 1.0,
            "weight_cap": None,
        },
        "control": {
            "name": "gold_bond_equal_50_50",
            "weights": GOLD_BOND_WEIGHTS,
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
            "full_max_drawdown_floor": -0.12,
            "full_sharpe_min": 0.90,
            "full_calmar_min": 0.40,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.15,
            "median_fold_sharpe_min": 0.65,
            "annual_turnover_max": 1.5,
            "quality_correlation_max": 0.35,
            "positive_years_min": 9,
            "return_shortfall_vs_gold_bond_max": 0.02,
            "drawdown_improvement_vs_gold_bond_min": 0.03,
            "sharpe_shortfall_vs_gold_bond_max": 0.05,
            "average_max_asset_weight_max": 0.85,
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
    """先登记计算语义和数据指纹，再加载基金行情。"""
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
        result, run, diagnostics = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, run, diagnostics)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun, pd.DataFrame]:
    """同一面板运行逆波动候选与黄金国债固定对照。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        ASSETS,
        start_date="20130101",
        end_date=as_of_date,
    )
    _validate_panel(panel, as_of_date)
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    targets, diagnostics = build_inverse_volatility_targets(
        panel.adjusted_close,
        signals,
        ASSETS,
        lookback_days=LOOKBACK_DAYS,
    )
    if len(targets) < 100:
        raise ValueError("逆波动目标组合不足100个月")
    control_targets = {
        date.strftime("%Y%m%d"): dict(GOLD_BOND_WEIGHTS)
        for date in signals
    }
    benchmark = _benchmark_curve(panel)
    model = ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0)
    runs = {
        STRATEGY_ID: run_risk_layer_backtest(
            STRATEGY_ID,
            "FIXED",
            targets,
            panel.bars,
            panel.calendar,
            benchmark,
            model,
        ),
        "黄金国债50/50": run_risk_layer_backtest(
            "黄金国债50/50",
            "FIXED",
            control_targets,
            panel.bars,
            panel.calendar,
            benchmark,
            model,
        ),
    }
    periods = {
        key: (start, panel.latest_common_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    candidate = runs[STRATEGY_ID]
    annual = build_annual_metrics(
        candidate,
        benchmark,
        panel.latest_common_date,
    )
    full_comparison = {
        name: values["full"] for name, values in metrics.items()
    }
    weight_diagnostics = summarize_weights(diagnostics)
    quality_correlation = load_quality_correlation(paths, candidate)
    gate = evaluate_gate(
        metrics[STRATEGY_ID],
        annual,
        quality_correlation,
        full_comparison,
        weight_diagnostics,
    )
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics[STRATEGY_ID],
        "annual_metrics": annual,
        "full_comparison": full_comparison,
        "weight_diagnostics": weight_diagnostics,
        "quality_return_correlation": quality_correlation,
        "gate": gate,
        "latest_holdings": (
            diagnostics[diagnostics["signal_date"].eq(diagnostics["signal_date"].max())]
            .to_dict("records")
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, candidate, diagnostics


def summarize_weights(diagnostics: pd.DataFrame) -> dict[str, dict[str, float]]:
    """汇总每类资产的平均、最新和历史最高权重。"""
    latest_date = str(diagnostics["signal_date"].max())
    latest = diagnostics[diagnostics["signal_date"].eq(latest_date)]
    return {
        str(symbol): {
            "average_weight": float(group["target_weight"].mean()),
            "latest_weight": float(
                latest.loc[latest["symbol"].eq(symbol), "target_weight"].iloc[0]
            ),
            "maximum_weight": float(group["target_weight"].max()),
        }
        for symbol, group in diagnostics.groupby("symbol", sort=True)
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
    full_comparison: dict[str, dict[str, float]],
    weight_diagnostics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """执行研究前冻结的风险效率、稳定性和增量价值门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    control = full_comparison["黄金国债50/50"]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    largest_average = max(
        item["average_weight"] for item in weight_diagnostics.values()
    )
    checks = {
        "full_annual_return_at_least_5pct": full["annualized_return"] >= 0.05,
        "full_drawdown_within_12pct": full["max_drawdown"] >= -0.12,
        "full_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "full_calmar_at_least_040": full["calmar"] >= 0.40,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_15pct": (
            min(item["max_drawdown"] for item in folds) >= -0.15
        ),
        "median_fold_sharpe_at_least_065": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.65
        ),
        "annual_turnover_below_15x": full["annual_turnover"] <= 1.5,
        "quality_correlation_at_most_035": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.35
        ),
        "at_least_nine_positive_years": positive_years >= 9,
        "return_shortfall_vs_gold_bond_within_2pct": (
            control["annualized_return"] - full["annualized_return"] <= 0.02
        ),
        "drawdown_improvement_vs_gold_bond_at_least_3pct": (
            full["max_drawdown"] - control["max_drawdown"] >= 0.03
        ),
        "sharpe_shortfall_vs_gold_bond_within_005": (
            control["sharpe"] - full["sharpe"] <= 0.05
        ),
        "average_largest_asset_weight_at_most_85pct": largest_average <= 0.85,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
        "largest_average_weight": largest_average,
    }


def _validate_panel(panel: FundPortfolioPanel, as_of_date: str) -> None:
    """阻止资产缺失、样本不足或数据滞后研究。"""
    symbols = {str(item["symbol"]) for item in panel.coverage}
    if symbols != set(ASSETS):
        raise ValueError("三资产基金面板不完整")
    if len(panel.calendar) < 2500:
        raise ValueError("三资产共同交易日不足2500天")
    lag = (pd.Timestamp(as_of_date) - pd.Timestamp(panel.latest_common_date)).days
    if lag < 0 or lag > 5:
        raise ValueError("三资产共同数据截止日滞后超过5个自然日")


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    values = panel.adjusted_close[EQUITY_SYMBOL].astype(float)
    return values / float(values.iloc[0])


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
    diagnostics: pd.DataFrame,
) -> None:
    """保存报告、净值和每月风险预算，失败结论同样可追溯。"""
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
    weights_path = attempt.output_dir / "monthly_risk_budget.csv"
    diagnostics.to_csv(weights_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "三资产逆波动风险预算通过多折门槛，可进入前瞻Paper确认"
            if passed
            else "三资产逆波动风险预算未通过固定门槛，不创建观察策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "逆波动研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值曲线"),
            ExperimentArtifact("monthly_risk_budget", weights_path, "月度风险预算"),
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
