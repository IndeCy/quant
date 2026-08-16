"""国内Quality与全球防守三资产各占半仓的固定杠铃研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.mixed_asset_execution import MixedAssetExecutionModel
from data.fund_portfolio import load_fund_portfolio_panel
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples import global_defensive_equal_study as global_study
from examples import quality_defensive_assets_study as quality_defensive
from examples import quality_quarterly_lowvol_blend_study as quality_support
from examples.quality_balanced_value_buffered_study import _data_version
from examples.quality_balanced_value_size_neutral_study import PERIODS
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
from portfolio.fixed_sleeve import build_core_scoped_sleeve_targets
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "quality_global_defensive_barbell_50_50_v1"
QUALITY_DEFENSIVE_ID = "quality_defensive_70_15_15_same_snapshot_v3"
GLOBAL_ID = "global_defensive_equal_same_snapshot_v2"
QUALITY_ID = "quality_balanced_value_core_same_snapshot_v2"
REPORT_PATH = Path(
    "docs/research/quality-global-defensive-barbell-50-50-v1.md"
)
QUALITY_WEIGHT = 0.50
FUND_WEIGHTS = {
    global_study.SP500_SYMBOL: 1 / 6,
    global_study.GOLD_SYMBOL: 1 / 6,
    global_study.BOND_SYMBOL: 1 / 6,
}
FUND_SYMBOLS = set(FUND_WEIGHTS)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="国内Quality×全球防守固定杠铃50/50 V1",
    category="portfolio_strategy",
    hypothesis="国内Quality Alpha与全球三资产防守块固定各半能否同时保留收益和显著降低单一市场回撤",
    definition={
        "quality_block": {
            "strategy": "quality_balanced_value_v1",
            "weight": QUALITY_WEIGHT,
            "definition_change": "none",
        },
        "global_defensive_block": {
            "weight": 0.50,
            "inside_block_equal_weight": {
                global_study.SP500_SYMBOL: 1 / 3,
                global_study.GOLD_SYMBOL: 1 / 3,
                global_study.BOND_SYMBOL: 1 / 3,
            },
        },
        "portfolio": {
            "weights": {
                "quality": QUALITY_WEIGHT,
                **FUND_WEIGHTS,
            },
            "allocation_grid": False,
            "rebalance": "quality_monthly_signal",
        },
        "risk_overlay": {
            "scope": "quality_block_only",
            "window": 20,
            "threshold": 0.45,
            "reduced_quality_exposure": 0.30,
            "global_defensive_budget_unchanged": True,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
            "stock_stamp_tax_rate": 0.001,
            "fund_stamp_tax_rate": 0.0,
        },
        "frozen_gate": {
            "full_annual_return_min": 0.10,
            "full_drawdown_floor": -0.18,
            "full_sharpe_min": 0.90,
            "full_calmar_min": 0.55,
            "all_four_folds_positive": True,
            "worst_fold_drawdown_floor": -0.20,
            "median_fold_sharpe_min": 0.50,
            "annual_turnover_max": 5.0,
            "locked_return_min": 0.09,
            "locked_sharpe_min": 0.70,
            "locked_drawdown_floor": -0.18,
            "return_shortfall_vs_quality_defensive_max": 0.01,
            "drawdown_improvement_vs_quality_defensive_min": 0.02,
            "sharpe_at_least_quality_defensive": True,
            "return_at_least_global_defensive": True,
            "quality_daily_correlation_max": 0.75,
            "global_daily_correlation_max": 0.90,
            "stress_20bps_return_min": 0.09,
            "stress_20bps_sharpe_min": 0.80,
            "positive_years_min": 9,
        },
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "fixed_domestic_global_barbell_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记固定50/50块权重后再读取点时财务和基金行情。"""
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
    funds = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*FUND_WEIGHTS, global_study.BENCHMARK_SYMBOL],
        start_date="20130101",
        end_date=as_of_date,
    )
    latest_date = funds.latest_common_date
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=latest_date,
    )
    try:
        materialize_market_features(connection)
        monthly_dates = [
            date
            for date in load_month_end_signal_dates(connection)
            if date >= "20150101"
        ]
        quality_targets, quality_holdings = quality_support._build_core(
            connection,
            monthly_dates,
            paths,
        )
        stock_symbols = sorted(
            {
                symbol
                for weights in quality_targets.values()
                for symbol in weights
            }
        )
        stock_bars = load_feature_bars(connection, stock_symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = quality_defensive._benchmark_curve(paths, latest_date)
    quality_run = quality_defensive._run_candidate(
        QUALITY_ID,
        quality_targets,
        stock_bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        risk_overlay=True,
    )
    quality_defensive_targets = build_core_scoped_sleeve_targets(
        quality_targets,
        quality_run.exposure,
        core_allocation=0.70,
        defensive_weights={
            global_study.GOLD_SYMBOL: 0.15,
            global_study.BOND_SYMBOL: 0.15,
        },
    )
    candidate_targets = build_core_scoped_sleeve_targets(
        quality_targets,
        quality_run.exposure,
        core_allocation=QUALITY_WEIGHT,
        defensive_weights=FUND_WEIGHTS,
    )
    global_targets = global_study._build_targets(
        [pd.Timestamp(date) for date in quality_targets],
        global_study.ASSET_WEIGHTS,
    )
    bars = pd.concat([stock_bars, funds.bars]).sort_index()
    mixed_model = MixedAssetExecutionModel(FUND_SYMBOLS, slippage_bps=5.0)
    quality_defensive_run = quality_defensive._run_candidate(
        QUALITY_DEFENSIVE_ID,
        quality_defensive_targets,
        bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    global_run = quality_defensive._run_candidate(
        GLOBAL_ID,
        global_targets,
        funds.bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    candidate_run = quality_defensive._run_candidate(
        EXPERIMENT_ID,
        candidate_targets,
        bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    stress_run = quality_defensive._run_candidate(
        f"{EXPERIMENT_ID}_20bps",
        candidate_targets,
        bars,
        calendar,
        benchmark,
        MixedAssetExecutionModel(FUND_SYMBOLS, slippage_bps=20.0),
        risk_overlay=False,
    )
    runs = {
        QUALITY_ID: quality_run,
        QUALITY_DEFENSIVE_ID: quality_defensive_run,
        GLOBAL_ID: global_run,
        EXPERIMENT_ID: candidate_run,
    }
    periods = {
        name: (
            start,
            latest_date if end == "latest" else min(end, latest_date),
        )
        for name, (start, end) in PERIODS.items()
        if start <= latest_date
    }
    metrics = build_period_metrics(
        {key: value.result for key, value in runs.items()},
        benchmark,
        periods,
    )
    stress = build_period_metrics(
        {"20bps": stress_run.result},
        benchmark,
        {"full": ("20150101", latest_date)},
    )["20bps"]["full"]
    annual = build_annual_metrics(
        {EXPERIMENT_ID: candidate_run},
        benchmark,
        latest_date,
    )[EXPERIMENT_ID]
    correlations = _correlations(runs)
    gate = evaluate_gate(metrics, annual, stress, correlations)
    names = (
        quality_holdings[["symbol", "name"]]
        .drop_duplicates("symbol", keep="last")
        .set_index("symbol")["name"]
        .to_dict()
    )
    latest_target_date = max(candidate_targets)
    latest_holdings = [
        {
            "signal_date": latest_target_date,
            "symbol": symbol,
            "name": names.get(symbol, _fund_name(symbol)),
            "target_weight": weight,
            "sleeve": "global_defensive" if symbol in FUND_SYMBOLS else "quality",
        }
        for symbol, weight in sorted(
            candidate_targets[latest_target_date].items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "metrics": metrics,
        "annual_metrics": annual,
        "stress_20bps_metrics": stress,
        "correlations": correlations,
        "gate": gate,
        "decision": (
            "HISTORICAL_GATE_PASSED_FORWARD_CONFIRMATION_ONLY"
            if gate["passed"]
            else "REJECTED_NO_PRODUCTION_CHANGE"
        ),
        "latest_holdings": latest_holdings,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    stress: dict[str, float],
    correlations: dict[str, float],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    quality_def = metrics[QUALITY_DEFENSIVE_ID]["full"]
    global_def = metrics[GLOBAL_ID]["full"]
    folds = [
        candidate[key]
        for key in ("2015_2017", "2018_2020", "2021_2023", "2024_latest")
    ]
    checks = {
        "full_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_drawdown_within_18pct": full["max_drawdown"] >= -0.18,
        "full_sharpe_at_least_090": full["sharpe"] >= 0.90,
        "full_calmar_at_least_055": full["calmar"] >= 0.55,
        "all_four_folds_positive": all(
            item["annualized_return"] > 0 for item in folds
        ),
        "worst_fold_drawdown_within_20pct": (
            min(item["max_drawdown"] for item in folds) >= -0.20
        ),
        "median_fold_sharpe_at_least_050": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.50
        ),
        "annual_turnover_below_5x": full["annual_turnover"] <= 5.0,
        "locked_return_at_least_9pct": locked["annualized_return"] >= 0.09,
        "locked_sharpe_at_least_070": locked["sharpe"] >= 0.70,
        "locked_drawdown_within_18pct": locked["max_drawdown"] >= -0.18,
        "return_within_1pct_of_quality_defensive": (
            full["annualized_return"] >= quality_def["annualized_return"] - 0.01
        ),
        "drawdown_improves_quality_defensive_by_2pct": (
            full["max_drawdown"] >= quality_def["max_drawdown"] + 0.02
        ),
        "sharpe_at_least_quality_defensive": (
            full["sharpe"] >= quality_def["sharpe"]
        ),
        "return_at_least_global_defensive": (
            full["annualized_return"] >= global_def["annualized_return"]
        ),
        "quality_daily_correlation_at_most_075": (
            abs(correlations["candidate_quality"]) <= 0.75
        ),
        "global_daily_correlation_at_most_090": (
            abs(correlations["candidate_global"]) <= 0.90
        ),
        "stress_20bps_return_at_least_9pct": (
            stress["annualized_return"] >= 0.09
        ),
        "stress_20bps_sharpe_at_least_080": stress["sharpe"] >= 0.80,
        "at_least_nine_positive_years": (
            sum(item["annualized_return"] > 0 for item in annual.values()) >= 9
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _correlations(runs: dict[str, RiskLayerRun]) -> dict[str, float]:
    returns = {
        key: value.result.daily_values.pct_change()
        for key, value in runs.items()
    }
    return {
        "candidate_quality": float(
            returns[EXPERIMENT_ID].corr(returns[QUALITY_ID])
        ),
        "candidate_global": float(
            returns[EXPERIMENT_ID].corr(returns[GLOBAL_ID])
        ),
        "quality_global": float(
            returns[QUALITY_ID].corr(returns[GLOBAL_ID])
        ),
    }


def _fund_name(symbol: str) -> str:
    return {
        global_study.SP500_SYMBOL: "博时标普500ETF",
        global_study.GOLD_SYMBOL: "华安黄金ETF",
        global_study.BOND_SYMBOL: "国泰5年国债ETF",
    }.get(symbol, "")


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
) -> None:
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.concat(
        [
            (run.result.daily_values / float(run.result.daily_values.iloc[0])).rename(
                strategy_id
            )
            for strategy_id, run in runs.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "固定国内全球杠铃通过全部门槛，仅进入冻结前瞻确认"
            if passed
            else "固定国内全球杠铃未通过全部门槛，不修改生产或观察策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "杠铃研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("latest_holdings", holdings_path, "最新目标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for strategy_id in (
        QUALITY_DEFENSIVE_ID,
        GLOBAL_ID,
        EXPERIMENT_ID,
    ):
        for period in (
            "2015_2017",
            "2018_2020",
            "2021_2023",
            "2024_latest",
            "locked_test",
            "full",
        ):
            item = result["metrics"][strategy_id][period]
            rows.append(
                f"| {strategy_id} | {period} | "
                f"{item['annualized_return']:.2%} | {item['max_drawdown']:.2%} | "
                f"{item['sharpe']:.3f} | {item['annual_turnover']:.2f}x |"
            )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'}：{key}"
        for key, value in result["gate"]["checks"].items()
    )
    stress = result["stress_20bps_metrics"]
    corr = result["correlations"]
    return f"""# 国内Quality×全球防守固定杠铃50/50 V1

- 数据截止：{result['latest_date']}
- 国内Quality 50%；标普500、黄金、5年国债各16.67%。
- Quality风险层只管理国内股票块；三个ETF固定预算。
- 没有权重网格，不自动修改观察策略或生产调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---|---:|---:|---:|---:|
{chr(10).join(rows)}

## 独立性和成本

- 候选与Quality/全球防守日收益相关：
  {corr['candidate_quality']:.3f} / {corr['candidate_global']:.3f}。
- Quality与全球防守日收益相关：{corr['quality_global']:.3f}。
- 20bps压力年化/Sharpe：
  {stress['annualized_return']:.2%} / {stress['sharpe']:.3f}。

## 冻结门槛

{checks}

结论：{result['decision']}。
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
