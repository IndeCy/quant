"""标普500、黄金和国债的月频动态逆波动配置研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from examples import global_defensive_equal_study as equal_study
from examples.cross_asset_dual_momentum_study import (
    FOLDS,
    STUDY_START,
    build_annual_metrics,
    load_quality_correlation,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
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


EXPERIMENT_ID = "global_defensive_inverse_volatility_60d_v1"
REPORT_PATH = Path("docs/research/global-defensive-inverse-volatility-60d-v1.md")
STRESS_ID = "global_defensive_inverse_volatility_60d_20bps"
EQUAL_CONTROL_ID = "global_defensive_equal_same_panel_control"
SP500_CONTROL_ID = "global_defensive_inverse_vol_sp500_control"
ASSETS = [
    equal_study.SP500_SYMBOL,
    equal_study.GOLD_SYMBOL,
    equal_study.BOND_SYMBOL,
]
LOOKBACK_DAYS = 60
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全球防守三资产60日逆波动 V1",
    category="allocation_strategy",
    hypothesis=(
        "标普500、黄金和国债按过去60个交易日逆波动月频配置，能否在不显著牺牲"
        "固定等权收益的前提下进一步降低回撤并保持独立性"
    ),
    definition={
        "dependency": equal_study.STRATEGY_ID,
        "assets": ASSETS,
        "portfolio": {
            "weighting": "inverse_annualized_volatility",
            "lookback_trading_days": LOOKBACK_DAYS,
            "rebalance": "monthly",
            "leverage": 1.0,
            "weight_cap": None,
        },
        "controls": {
            EQUAL_CONTROL_ID: dict(equal_study.ASSET_WEIGHTS),
            SP500_CONTROL_ID: {equal_study.SP500_SYMBOL: 1.0},
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stamp_tax_rate": 0.0,
        },
        "gate": {
            "full_return_min": 0.085,
            "full_drawdown_floor": -0.15,
            "full_sharpe_min": 1.05,
            "full_calmar_min": 0.55,
            "return_shortfall_vs_equal_max": 0.015,
            "drawdown_improvement_vs_equal_min": 0.005,
            "sharpe_shortfall_vs_equal_max": 0.05,
            "drawdown_improvement_vs_sp500_min": 0.10,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.18,
            "median_fold_sharpe_min": 0.75,
            "positive_years_min": 8,
            "annual_turnover_max": 1.5,
            "quality_correlation_max": 0.30,
            "largest_average_weight_max": 0.70,
            "stress_return_min": 0.08,
            "stress_drawdown_floor": -0.16,
            "stress_sharpe_min": 1.00,
        },
        "parameter_grid": False,
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "forward_paper_only",
        "methodology_version": "global_inverse_vol_multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记完整研究定义与数据指纹后再加载价格。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=equal_study._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_equal_dependency(paths)
        result, runs, diagnostics = calculate(paths, as_of_date)
        complete_attempt(attempt, result, runs[EXPERIMENT_ID], diagnostics)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun], pd.DataFrame]:
    """在同一基金面板上运行候选、压力场景与固定对照。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*ASSETS, equal_study.BENCHMARK_SYMBOL],
        start_date="20130101",
        end_date=as_of_date,
    )
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
        raise ValueError("全球三资产逆波动有效月度目标不足100期")
    controls = {
        EQUAL_CONTROL_ID: equal_study._build_targets(
            signals,
            equal_study.ASSET_WEIGHTS,
        ),
        SP500_CONTROL_ID: equal_study._build_targets(
            signals,
            {equal_study.SP500_SYMBOL: 1.0},
        ),
    }
    target_sets = {
        EXPERIMENT_ID: targets,
        STRESS_ID: targets,
        **controls,
    }
    benchmark = equal_study._benchmark_curve(panel)
    runs = {
        name: run_risk_layer_backtest(
            name,
            "FIXED",
            target,
            panel.bars,
            panel.calendar,
            benchmark,
            ExecutionModel(
                stamp_tax_rate=0.0,
                slippage_bps=20.0 if name == STRESS_ID else 5.0,
            ),
        )
        for name, target in target_sets.items()
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
    annual = build_annual_metrics(
        runs[EXPERIMENT_ID],
        benchmark,
        panel.latest_common_date,
    )
    weights = summarize_weights(diagnostics)
    quality_correlation = load_quality_correlation(paths, runs[EXPERIMENT_ID])
    gate = evaluate_gate(metrics, annual, quality_correlation, weights)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "period_metrics": metrics[EXPERIMENT_ID],
        "annual_metrics": annual,
        "full_comparison": {
            name: values["full"]
            for name, values in metrics.items()
        },
        "weight_diagnostics": weights,
        "quality_return_correlation": quality_correlation,
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, diagnostics


def summarize_weights(diagnostics: pd.DataFrame) -> dict[str, dict[str, float]]:
    """汇总动态目标，确认没有资产长期垄断风险预算。"""
    latest_date = diagnostics["signal_date"].max()
    latest = diagnostics[diagnostics["signal_date"].eq(latest_date)]
    return {
        str(symbol): {
            "average_weight": float(group["target_weight"].mean()),
            "latest_weight": float(
                latest.loc[
                    latest["symbol"].eq(symbol),
                    "target_weight",
                ].iloc[0]
            ),
            "maximum_weight": float(group["target_weight"].max()),
        }
        for symbol, group in diagnostics.groupby("symbol", sort=True)
    }


def evaluate_gate(
    all_metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
    weights: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """应用预注册的绝对、相对、稳定性和成本门槛。"""
    candidate = all_metrics[EXPERIMENT_ID]
    full = candidate["full"]
    stress = all_metrics[STRESS_ID]["full"]
    equal = all_metrics[EQUAL_CONTROL_ID]["full"]
    sp500 = all_metrics[SP500_CONTROL_ID]["full"]
    folds = [candidate[key] for key in FOLDS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    largest_average = max(
        item["average_weight"] for item in weights.values()
    )
    checks = {
        "full_return_at_least_85pct": full["annualized_return"] >= 0.085,
        "full_drawdown_within_15pct": full["max_drawdown"] >= -0.15,
        "full_sharpe_at_least_105": full["sharpe"] >= 1.05,
        "full_calmar_at_least_055": full["calmar"] >= 0.55,
        "return_shortfall_vs_equal_within_15pct": (
            equal["annualized_return"] - full["annualized_return"] <= 0.015
        ),
        "drawdown_improvement_vs_equal_at_least_05pct": (
            full["max_drawdown"] - equal["max_drawdown"] >= 0.005
        ),
        "sharpe_shortfall_vs_equal_within_005": (
            equal["sharpe"] - full["sharpe"] <= 0.05
        ),
        "drawdown_improvement_vs_sp500_at_least_10pct": (
            full["max_drawdown"] - sp500["max_drawdown"] >= 0.10
        ),
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_18pct": (
            min(item["max_drawdown"] for item in folds) >= -0.18
        ),
        "median_fold_sharpe_at_least_075": (
            float(pd.Series([item["sharpe"] for item in folds]).median())
            >= 0.75
        ),
        "at_least_eight_positive_years": positive_years >= 8,
        "annual_turnover_below_15x": full["annual_turnover"] <= 1.5,
        "quality_correlation_at_most_030": (
            pd.notna(quality_correlation)
            and abs(quality_correlation) <= 0.30
        ),
        "largest_average_weight_at_most_70pct": largest_average <= 0.70,
        "stress_return_at_least_8pct": stress["annualized_return"] >= 0.08,
        "stress_drawdown_within_16pct": stress["max_drawdown"] >= -0.16,
        "stress_sharpe_at_least_100": stress["sharpe"] >= 1.00,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
        "largest_average_weight": largest_average,
    }


def require_equal_dependency(paths: RuntimePaths) -> None:
    """只允许从已过门槛的固定等权研究继续。"""
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        equal_study.STRATEGY_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("全球防守固定等权依赖未成功完成")
    if latest.get("outcome") != "PASSED_RESEARCH_GATE":
        raise RuntimeError("全球防守固定等权依赖未通过研究门槛")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    diagnostics: pd.DataFrame,
) -> None:
    """持久化报告、净值和月度风险预算。"""
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
            "全球三资产逆波动通过固定门槛，仅进入前瞻Paper确认"
            if passed
            else "全球三资产逆波动未通过固定门槛，不生成参数变体"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "逆波动研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "每日净值"),
            ExperimentArtifact(
                "monthly_risk_budget",
                weights_path,
                "月度动态风险预算",
            ),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """渲染可审计研究摘要。"""
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['annual_turnover']:.2f}x |"
        for name, item in result["period_metrics"].items()
    )
    comparisons = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    weight_rows = "\n".join(
        f"| {symbol} | {item['average_weight']:.1%} | "
        f"{item['latest_weight']:.1%} | {item['maximum_weight']:.1%} |"
        for symbol, item in result["weight_diagnostics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 全球防守三资产60日逆波动 V1

- 数据共同截止：{result['latest_date']}。
- 资产固定为标普500ETF、黄金ETF和5年国债ETF。
- 月末按过去60个交易日年化波动率倒数归一化；无杠杆、无权重上限、无参数网格。
- M0 T+1、qfq、基础5bps并独立验证20bps压力；ETF免印花税。
- 与Quality日收益相关性：{result['quality_return_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{periods}

## 同口径对照与压力

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{comparisons}

## 动态权重诊断

| 代码 | 平均权重 | 最新权重 | 历史最高权重 |
|---|---:|---:|---:|
{weight_rows}

## 冻结门槛

{checks}

结论：{'通过固定门槛，仅允许进入前瞻Paper确认' if result['gate']['passed'] else '未通过固定门槛，终止该路线且不生成参数变体'}。
"""


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
