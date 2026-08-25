"""Quality核心叠加黄金与国债固定防守袖套的证券级研究。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
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
from examples.quality_defensive_assets_report import render_report
from examples import quality_quarterly_lowvol_blend_study as quality_support
from examples.quality_factor_study_support import (
    build_period_metrics,
)
from examples.quality_defensive_assets_metrics import (
    build_annual_metrics,
    build_correlations,
    build_risk_path_diagnostics,
    evaluate_gate,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from portfolio.fixed_sleeve import blend_fixed_sleeve_targets
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "quality_defensive_assets_70_15_15_v1"
CORE_ID = "quality_balanced_value_core_same_snapshot_v1"
DEFENSIVE_ID = "gold_bond_equal_sleeve_v1"
REPORT_PATH = Path("docs/research/quality-defensive-assets-70-15-15-v1.md")
CORE_ALLOCATION = 0.70
GOLD_SYMBOL = "518880.SH"
BOND_SYMBOL = "511010.SH"
DEFENSIVE_WEIGHTS = {GOLD_SYMBOL: 0.15, BOND_SYMBOL: 0.15}
FUND_SYMBOLS = set(DEFENSIVE_WEIGHTS)
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality+黄金国债70/15/15 V1",
    category="portfolio_strategy",
    hypothesis="固定黄金与国债袖套能否在少量收益损失下显著降低Quality核心回撤",
    definition={
        "core": {
            "strategy": "quality_balanced_value_v1",
            "allocation": CORE_ALLOCATION,
            "definition_change": "none",
        },
        "defensive_sleeve": {
            GOLD_SYMBOL: 0.15,
            BOND_SYMBOL: 0.15,
            "selection_basis": "economic_role_fixed_before_backtest",
        },
        "portfolio": {
            "rebalance": "on_quality_monthly_signal",
            "combine_level": "security_target_weights",
            "cash": "only_from_existing_portfolio_risk_overlay",
        },
        "risk_overlay": {
            "scheme": "GRID",
            "scope": "whole_portfolio",
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
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
            "annual_return_shortfall_vs_core_max": 0.025,
            "sharpe_not_below_core": True,
            "defensive_correlation_to_core_max": 0.30,
        },
        "promotion_scope": "research_only",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记固定组合指纹，再读取财务和行情大表。"""
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
        result, runs, latest_holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, runs, latest_holdings)
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
]:
    """在同一截止日重建核心、固定防守袖套和证券级组合。"""
    fund_panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [GOLD_SYMBOL, BOND_SYMBOL],
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
        blend_targets = blend_fixed_sleeve_targets(
            core_targets,
            core_allocation=CORE_ALLOCATION,
            defensive_weights=DEFENSIVE_WEIGHTS,
        )
        defensive_targets = {
            date: {GOLD_SYMBOL: 0.5, BOND_SYMBOL: 0.5}
            for date in core_targets
        }
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

    bars = pd.concat([stock_bars, fund_panel.bars]).sort_index()
    benchmark = _benchmark_curve(paths, latest_date)
    stock_model = ExecutionModel(slippage_bps=5.0)
    mixed_model = MixedAssetExecutionModel(FUND_SYMBOLS, slippage_bps=5.0)
    runs = {
        CORE_ID: _run_candidate(
            CORE_ID,
            core_targets,
            stock_bars,
            calendar,
            benchmark,
            stock_model,
            risk_overlay=True,
        ),
        DEFENSIVE_ID: _run_candidate(
            DEFENSIVE_ID,
            defensive_targets,
            fund_panel.bars,
            calendar,
            benchmark,
            mixed_model,
            risk_overlay=False,
        ),
        STRATEGY_ID: _run_candidate(
            STRATEGY_ID,
            blend_targets,
            bars,
            calendar,
            benchmark,
            mixed_model,
            risk_overlay=True,
        ),
    }
    periods = {
        key: (start, latest_date if end == "LATEST" else end)
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = ("20150101", latest_date)
    metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs, benchmark, latest_date)
    correlations = build_correlations(
        runs,
        core_id=CORE_ID,
        defensive_id=DEFENSIVE_ID,
        blend_id=STRATEGY_ID,
    )
    risk_path = build_risk_path_diagnostics(
        runs,
        core_id=CORE_ID,
        blend_id=STRATEGY_ID,
    )
    gate = evaluate_gate(
        metrics[STRATEGY_ID],
        metrics[CORE_ID],
        annual[STRATEGY_ID],
        correlations,
    )
    latest_holdings = build_latest_holdings(
        core_targets,
        core_holdings,
        latest_date=max(core_targets),
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            annual,
            gate,
            correlations,
            risk_path,
            latest_date,
            blend_id=STRATEGY_ID,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": latest_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "correlations": correlations,
            "risk_path": risk_path,
            "gate": gate,
            "latest_holdings": latest_holdings.to_dict("records"),
            "data_coverage": fund_panel.coverage,
            "promotion_allowed": False,
            "report_path": str(report_path),
            "reused": False,
        },
        runs,
        latest_holdings,
    )


def _benchmark_curve(paths: RuntimePaths, latest_date: str) -> pd.Series:
    """继续使用系统统一的510300复权基准。"""
    from data.benchmark_series import load_adjusted_fund_curve

    return load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )


def _run_candidate(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
    execution_model: ExecutionModel,
    *,
    risk_overlay: bool,
) -> RiskLayerRun:
    """三条腿使用同一回测引擎，仅防守袖套不叠加组合风险层。"""
    return run_risk_layer_backtest(
        strategy_id,
        "GRID" if risk_overlay else "FIXED",
        targets,
        bars,
        calendar,
        benchmark,
        execution_model,
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )


def build_latest_holdings(
    core_targets: dict[str, dict[str, float]],
    core_holdings: pd.DataFrame,
    *,
    latest_date: str,
) -> pd.DataFrame:
    """输出最新证券级目标及袖套来源。"""
    names = (
        core_holdings[["symbol", "name"]]
        .drop_duplicates("symbol", keep="last")
        .set_index("symbol")["name"]
        .to_dict()
    )
    rows = [
        {
            "signal_date": latest_date,
            "symbol": symbol,
            "name": names.get(symbol, ""),
            "target_weight": CORE_ALLOCATION * weight,
            "sleeve": "quality_core",
        }
        for symbol, weight in core_targets[latest_date].items()
    ]
    rows.extend(
        [
            {
                "signal_date": latest_date,
                "symbol": GOLD_SYMBOL,
                "name": "黄金ETF",
                "target_weight": DEFENSIVE_WEIGHTS[GOLD_SYMBOL],
                "sleeve": "defensive_gold",
            },
            {
                "signal_date": latest_date,
                "symbol": BOND_SYMBOL,
                "name": "5年国债ETF",
                "target_weight": DEFENSIVE_WEIGHTS[BOND_SYMBOL],
                "sleeve": "defensive_bond",
            },
        ]
    )
    return pd.DataFrame(rows).sort_values(
        ["target_weight", "symbol"],
        ascending=[False, True],
    )


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    holdings: pd.DataFrame,
) -> None:
    """归档报告、三条净值和最新证券级目标。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.concat(
        [
            (
                run.result.daily_values
                / float(run.result.daily_values.iloc[0])
            ).rename(strategy_id)
            for strategy_id, run in runs.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "固定70/15/15证券级组合通过门槛，只允许进入前瞻确认"
            if passed
            else "固定防守资产组合未通过门槛，不进入生产"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "防守资产组合报告"),
            ExperimentArtifact("daily_nav", nav_path, "核心、防守和组合净值"),
            ExperimentArtifact("latest_holdings", holdings_path, "最新证券级目标"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定证券级重放依赖的行情、财务和基金文件。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_market", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
        ("fina_indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
    ]:
        if not path.exists():
            parts.append(f"{label}:missing")
            continue
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
