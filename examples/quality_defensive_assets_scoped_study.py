"""Quality核心袖套独立风险预算的证券级研究。"""

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
from examples import quality_defensive_assets_study as base_study
from examples import quality_quarterly_lowvol_blend_study as quality_support
from examples.quality_defensive_assets_metrics import (
    build_annual_metrics,
    evaluate_scoped_gate,
)
from examples.quality_defensive_assets_scoped_report import render_scoped_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
from portfolio.fixed_sleeve import (
    blend_fixed_sleeve_targets,
    build_core_scoped_sleeve_targets,
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


STRATEGY_ID = "quality_defensive_assets_core_scoped_70_15_15_v2"
WHOLE_OVERLAY_ID = "quality_defensive_assets_whole_overlay_same_snapshot_v1"
CORE_ID = base_study.CORE_ID
DEFENSIVE_ID = base_study.DEFENSIVE_ID
REPORT_PATH = Path(
    "docs/research/quality-defensive-assets-core-scoped-70-15-15-v2.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套风险预算V2",
    category="portfolio_strategy",
    hypothesis="风险层仅管理Quality核心能否消除防守资产对波动阈值的稀释",
    definition={
        "alpha": {
            "strategy": "quality_balanced_value_v1",
            "definition_change": "none",
        },
        "fixed_budget": {
            "quality_core": 0.70,
            "518880.SH": 0.15,
            "511010.SH": 0.15,
        },
        "risk_overlay": {
            "scope": "quality_core_only",
            "window": 20,
            "threshold": 0.45,
            "reduced_core_exposure": 0.30,
            "normal_total_exposure": 1.00,
            "reduced_total_exposure": 0.51,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
            "stock_stamp_tax_rate": 0.001,
            "fund_stamp_tax_rate": 0.0,
        },
        "gate": {
            "full_annual_return_min": 0.10,
            "full_max_drawdown_floor": -0.25,
            "full_sharpe_min": 0.65,
            "full_calmar_min": 0.40,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.35,
            "annual_turnover_max": 8.0,
            "drawdown_improvement_vs_core_min": 0.03,
            "drawdown_improvement_vs_whole_overlay_min": 0.05,
            "annual_return_shortfall_vs_core_max": 0.025,
            "sharpe_not_below_core": True,
            "positive_years_min": 9,
        },
        "promotion_scope": "research_only",
        "methodology_version": "v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记独立指纹后再读取行情和财务大表。"""
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
        result, runs, exposure, holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs, exposure, holdings)
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
    pd.DataFrame,
    pd.DataFrame,
]:
    """同一数据快照下比较整组合与核心袖套两种风险作用域。"""
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
    stock_model = ExecutionModel(slippage_bps=5.0)
    mixed_model = MixedAssetExecutionModel(base_study.FUND_SYMBOLS, slippage_bps=5.0)
    core_run = base_study._run_candidate(
        CORE_ID,
        core_targets,
        stock_bars,
        calendar,
        benchmark,
        stock_model,
        risk_overlay=True,
    )
    defensive_targets = {
        date: {
            base_study.GOLD_SYMBOL: 0.5,
            base_study.BOND_SYMBOL: 0.5,
        }
        for date in core_targets
    }
    defensive_run = base_study._run_candidate(
        DEFENSIVE_ID,
        defensive_targets,
        fund_panel.bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    bars = pd.concat([stock_bars, fund_panel.bars]).sort_index()
    whole_targets = blend_fixed_sleeve_targets(
        core_targets,
        core_allocation=base_study.CORE_ALLOCATION,
        defensive_weights=base_study.DEFENSIVE_WEIGHTS,
    )
    whole_run = base_study._run_candidate(
        WHOLE_OVERLAY_ID,
        whole_targets,
        bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=True,
    )
    scoped_targets = build_core_scoped_sleeve_targets(
        core_targets,
        core_run.exposure,
        core_allocation=base_study.CORE_ALLOCATION,
        defensive_weights=base_study.DEFENSIVE_WEIGHTS,
    )
    scoped_run = base_study._run_candidate(
        STRATEGY_ID,
        scoped_targets,
        bars,
        calendar,
        benchmark,
        mixed_model,
        risk_overlay=False,
    )
    runs = {
        CORE_ID: core_run,
        DEFENSIVE_ID: defensive_run,
        WHOLE_OVERLAY_ID: whole_run,
        STRATEGY_ID: scoped_run,
    }
    result = _build_result(
        paths,
        latest_date,
        benchmark,
        runs,
        core_run.exposure,
        scoped_targets,
        core_holdings,
        fund_panel.coverage,
    )
    exposure = build_exposure_frame(core_run.exposure)
    holdings = build_latest_scoped_holdings(scoped_targets, core_holdings)
    return result, runs, exposure, holdings


def _build_result(
    paths: RuntimePaths,
    latest_date: str,
    benchmark: pd.Series,
    runs: dict[str, RiskLayerRun],
    core_exposure: pd.Series,
    scoped_targets: dict[str, dict[str, float]],
    core_holdings: pd.DataFrame,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    """计算分段、年度和门槛，并生成可读报告。"""
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in base_study.FOLDS.items()
    }
    periods["full"] = ("20150101", latest_date)
    metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs, benchmark, latest_date)
    gate = evaluate_scoped_gate(
        metrics[STRATEGY_ID],
        metrics[CORE_ID],
        metrics[WHOLE_OVERLAY_ID],
        annual[STRATEGY_ID],
    )
    holdings = build_latest_scoped_holdings(scoped_targets, core_holdings)
    latest_core_exposure = float(core_exposure.iloc[-1])
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_scoped_report(
            metrics,
            annual,
            gate,
            latest_date,
            scoped_id=STRATEGY_ID,
            core_id=CORE_ID,
            whole_id=WHOLE_OVERLAY_ID,
        ),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "gate": gate,
        "latest_core_exposure": latest_core_exposure,
        "latest_total_target": 0.30 + 0.70 * latest_core_exposure,
        "latest_holdings": holdings.to_dict("records"),
        "data_coverage": coverage,
        "promotion_allowed": False,
        "report_path": str(report_path),
        "reused": False,
    }


def build_exposure_frame(core_exposure: pd.Series) -> pd.DataFrame:
    """保存核心风险状态和组合有效总仓位。"""
    frame = core_exposure.rename("quality_core_exposure").to_frame()
    frame["effective_total_exposure"] = 0.30 + 0.70 * frame["quality_core_exposure"]
    return frame.rename_axis("trade_date").reset_index()


def build_latest_scoped_holdings(
    scoped_targets: dict[str, dict[str, float]],
    core_holdings: pd.DataFrame,
) -> pd.DataFrame:
    """输出最近一次核心风险事件后的证券级目标。"""
    signal_date = max(scoped_targets)
    names = (
        core_holdings[["symbol", "name"]]
        .drop_duplicates("symbol", keep="last")
        .set_index("symbol")["name"]
        .to_dict()
    )
    names.update(
        {
            base_study.GOLD_SYMBOL: "黄金ETF",
            base_study.BOND_SYMBOL: "5年国债ETF",
        }
    )
    rows = []
    for symbol, weight in scoped_targets[signal_date].items():
        sleeve = "quality_core"
        if symbol == base_study.GOLD_SYMBOL:
            sleeve = "defensive_gold"
        elif symbol == base_study.BOND_SYMBOL:
            sleeve = "defensive_bond"
        rows.append(
            {
                "signal_date": signal_date,
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "target_weight": float(weight),
                "sleeve": sleeve,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["target_weight", "symbol"],
        ascending=[False, True],
    )


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    exposure: pd.DataFrame,
    holdings: pd.DataFrame,
) -> None:
    """归档报告、净值、有效仓位和最近目标。"""
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
    exposure_path = attempt.output_dir / "effective_exposure.csv"
    exposure.to_csv(exposure_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "核心袖套风险预算通过冻结门槛，仅进入前瞻验证"
            if passed
            else "核心袖套风险预算未通过冻结门槛，不进入生产"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "袖套级风险预算报告"),
            ExperimentArtifact("daily_nav", nav_path, "四种口径净值"),
            ExperimentArtifact("effective_exposure", exposure_path, "有效风险仓位"),
            ExperimentArtifact("latest_holdings", holdings_path, "最新证券级目标"),
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
