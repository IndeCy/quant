"""Quality核心袖套风险预算的非优化鲁棒性确认。"""

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
from examples import quality_defensive_assets_scoped_study as scoped_study
from examples import quality_defensive_assets_study as base_study
from examples import quality_quarterly_lowvol_blend_study as quality_support
from examples.quality_defensive_assets_metrics import (
    build_annual_metrics,
    evaluate_robustness_gate,
)
from examples.quality_defensive_assets_robustness_report import (
    SCENARIO_NAMES,
    render_robustness_report,
)
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


STRATEGY_ID = "quality_defensive_assets_core_scoped_robustness_v1"
BASELINE_ID = "baseline_70_15_15"
NEIGHBORHOOD_IDS = ("neighbor_60_20_20", "neighbor_80_10_10")
COST_STRESS_IDS = ("slippage_10bps", "slippage_20bps")
DELAY_ID = "risk_delay_one_day"
SINGLE_ASSET_IDS = ("gold_only_70_30", "bond_only_70_30")
REPORT_PATH = Path(
    "docs/research/quality-defensive-assets-core-scoped-robustness-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套鲁棒性确认V1",
    category="portfolio_robustness",
    hypothesis="已冻结的核心袖套方案能否经受权重、成本、延迟和资产依赖压力",
    definition={
        "baseline": {
            "quality_core": 0.70,
            "518880.SH": 0.15,
            "511010.SH": 0.15,
        },
        "risk_overlay": {
            "scope": "quality_core_only",
            "window": 20,
            "threshold": 0.45,
            "reduced_core_exposure": 0.30,
        },
        "scenarios": {
            "neighbor_weights": ["60/20/20", "80/10/10"],
            "single_defensive_asset": ["70/30_gold", "70/30_bond"],
            "slippage_bps": [10.0, 20.0],
            "extra_risk_signal_delay_trading_days": 1,
        },
        "selection_rule": "no_best_scenario_selection",
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "baseline_slippage_bps": 5.0,
            "stock_stamp_tax_rate": 0.001,
            "fund_stamp_tax_rate": 0.0,
        },
        "gate": {
            "baseline": "annual>=10%, drawdown>=-25%, sharpe>=0.65",
            "neighbors_cost_delay": "annual>=9%, drawdown>=-25%, sharpe>=0.60",
            "single_asset": "annual>=8%, drawdown>=-30%, sharpe>=0.50",
            "all_scenarios_turnover_max": 8.0,
            "positive_baseline_years_min": 9,
        },
        "promotion_scope": "paper_candidate_only",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在读取大表前登记冻结场景和数据版本。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=base_study._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, runs, holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, RiskLayerRun], pd.DataFrame]:
    """重建点时核心信号，并在相同快照上执行全部冻结场景。"""
    fund_panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [base_study.GOLD_SYMBOL, base_study.BOND_SYMBOL],
        start_date="20130101",
        end_date=as_of_date,
    )
    latest_date = fund_panel.latest_common_date
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=latest_date,
    )
    try:
        materialize_market_features(connection)
        monthly_dates = load_month_end_signal_dates(connection)
        core_targets, core_holdings = quality_support._build_core(
            connection,
            monthly_dates,
            paths,
        )
        stock_symbols = sorted(
            {
                symbol
                for weights in core_targets.values()
                for symbol in weights
            }
        )
        stock_bars = load_feature_bars(connection, stock_symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = base_study._benchmark_curve(paths, latest_date)
    core_run = base_study._run_candidate(
        "quality_core_risk_signal",
        core_targets,
        stock_bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        risk_overlay=True,
    )
    bars = pd.concat([stock_bars, fund_panel.bars]).sort_index()
    runs = build_scenario_runs(
        core_targets,
        core_run.exposure,
        bars,
        calendar,
        benchmark,
    )
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in base_study.FOLDS.items()
    }
    periods["full"] = ("20150101", latest_date)
    metrics = build_period_metrics(
        {scenario_id: run.result for scenario_id, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs, benchmark, latest_date)
    gate = evaluate_robustness_gate(
        metrics,
        annual,
        baseline_id=BASELINE_ID,
        neighborhood_ids=NEIGHBORHOOD_IDS,
        cost_stress_ids=COST_STRESS_IDS,
        delay_id=DELAY_ID,
        single_asset_ids=SINGLE_ASSET_IDS,
    )
    baseline_targets = _targets(
        core_targets,
        core_run.exposure,
        core_allocation=0.70,
        gold_weight=0.15,
        bond_weight=0.15,
    )
    holdings = scoped_study.build_latest_scoped_holdings(
        baseline_targets,
        core_holdings,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_robustness_report(metrics, gate, latest_date),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": latest_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "gate": gate,
            "scenario_definitions": SCENARIO_NAMES,
            "promotion_allowed": False,
            "paper_candidate": bool(gate["passed"]),
            "report_path": str(report_path),
            "reused": False,
        },
        runs,
        holdings,
    )


def build_scenario_runs(
    core_targets: dict[str, dict[str, float]],
    core_exposure: pd.Series,
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> dict[str, RiskLayerRun]:
    """执行冻结场景；结果不用于选择新的权重参数。"""
    target_sets = {
        BASELINE_ID: _targets(core_targets, core_exposure, 0.70, 0.15, 0.15),
        "neighbor_60_20_20": _targets(
            core_targets, core_exposure, 0.60, 0.20, 0.20
        ),
        "neighbor_80_10_10": _targets(
            core_targets, core_exposure, 0.80, 0.10, 0.10
        ),
        "gold_only_70_30": _targets(
            core_targets, core_exposure, 0.70, 0.30, 0.00
        ),
        "bond_only_70_30": _targets(
            core_targets, core_exposure, 0.70, 0.00, 0.30
        ),
    }
    delayed_exposure = shift_exposure_one_trading_day(core_exposure)
    target_sets[DELAY_ID] = _targets(
        core_targets,
        delayed_exposure,
        0.70,
        0.15,
        0.15,
    )
    target_sets["slippage_10bps"] = target_sets[BASELINE_ID]
    target_sets["slippage_20bps"] = target_sets[BASELINE_ID]
    slippage = {
        "slippage_10bps": 10.0,
        "slippage_20bps": 20.0,
    }
    return {
        scenario_id: base_study._run_candidate(
            scenario_id,
            targets,
            bars,
            calendar,
            benchmark,
            MixedAssetExecutionModel(
                base_study.FUND_SYMBOLS,
                slippage_bps=slippage.get(scenario_id, 5.0),
            ),
            risk_overlay=False,
        )
        for scenario_id, targets in target_sets.items()
    }


def shift_exposure_one_trading_day(core_exposure: pd.Series) -> pd.Series:
    """压力测试：风险状态确认额外延迟一个交易日。"""
    return core_exposure.sort_index().shift(1).fillna(1.0)


def _targets(
    core_targets: dict[str, dict[str, float]],
    core_exposure: pd.Series,
    core_allocation: float,
    gold_weight: float,
    bond_weight: float,
) -> dict[str, dict[str, float]]:
    """按场景预算生成证券级目标。"""
    defensive = {}
    if gold_weight > 0:
        defensive[base_study.GOLD_SYMBOL] = gold_weight
    if bond_weight > 0:
        defensive[base_study.BOND_SYMBOL] = bond_weight
    return build_core_scoped_sleeve_targets(
        core_targets,
        core_exposure,
        core_allocation=core_allocation,
        defensive_weights=defensive,
    )


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    holdings: pd.DataFrame,
) -> None:
    """归档报告、全部场景净值、指标矩阵和基准持仓。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.concat(
        [
            (run.result.daily_values / float(run.result.daily_values.iloc[0])).rename(
                scenario_id
            )
            for scenario_id, run in runs.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    metrics_path = attempt.output_dir / "scenario_metrics.csv"
    pd.DataFrame(
        [
            {"scenario_id": scenario_id, **periods["full"]}
            for scenario_id, periods in result["period_metrics"].items()
        ]
    ).to_csv(metrics_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "冻结主方案通过全部鲁棒性门槛，可进入长期Paper观察"
            if passed
            else "冻结主方案未通过鲁棒性门槛，不进入Paper"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "鲁棒性确认报告"),
            ExperimentArtifact("daily_nav", nav_path, "全部压力场景净值"),
            ExperimentArtifact("scenario_metrics", metrics_path, "场景指标矩阵"),
            ExperimentArtifact("latest_holdings", holdings_path, "基准方案最新目标"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
