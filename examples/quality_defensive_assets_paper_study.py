"""Quality防守袖套策略的历史Paper可执行性研究。"""

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
from backtest.paper_execution import (
    BrokerConfig,
    BrokerSimulator,
    PaperTradingEngine,
    PaperTradingResult,
)
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
from examples.quality_defensive_assets_paper_metrics import (
    evaluate_paper_gate,
    execution_diagnostics,
    paper_curve,
    paper_metric_summary,
)
from examples.quality_defensive_assets_paper_report import render_paper_report
from examples.quality_factor_study_support import metric_summary, slice_result
from examples.quality_risk_layer_research import RiskLayerRun
from examples.strategy_comparison_research import BacktestResearchResult
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


STRATEGY_ID = "quality_defensive_assets_paper_feasibility_v1"
M0_ID = "m0_baseline"
PAPER_BASELINE_ID = "paper_baseline"
PAPER_STRESS_ID = "paper_stress"
INITIAL_CASH = 1_000_000.0
REPORT_PATH = Path(
    "docs/research/quality-defensive-assets-paper-feasibility-v1.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality防守袖套Paper可执行性V1",
    category="paper_feasibility",
    hypothesis="冻结策略在部分成交、流动性、费用和延迟后能否保持可执行",
    definition={
        "strategy": {
            "quality_core": 0.70,
            "518880.SH": 0.15,
            "511010.SH": 0.15,
            "risk_scope": "quality_core_only",
            "risk_window": 20,
            "risk_threshold": 0.45,
            "reduced_core_exposure": 0.30,
        },
        "capital": INITIAL_CASH,
        "paper_baseline": {
            "execution_delay": 1,
            "slippage_bps": 10.0,
            "max_participation_rate": 0.01,
        },
        "paper_stress": {
            "execution_delay": 2,
            "slippage_bps": 20.0,
            "max_participation_rate": 0.002,
        },
        "fees": {
            "commission_rate": 0.0003,
            "min_commission": 5.0,
            "stock_stamp_tax_rate": 0.001,
            "fund_stamp_tax_rate": 0.0,
            "lot_size": 100,
        },
        "partial_fill_policy": "unfilled_remainder_expires",
        "data": {"adjust": "qfq", "financial_visibility": "as_of"},
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
    """登记执行口径指纹后再读取行情和财务大表。"""
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
        result, m0_run, paper_runs, market_data = _calculate(paths, as_of_date)
        _complete_attempt(
            attempt,
            result,
            m0_run,
            paper_runs,
            market_data,
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
    RiskLayerRun,
    dict[str, PaperTradingResult],
    pd.DataFrame,
]:
    """同一数据快照下运行M0、正常Paper和压力Paper。"""
    latest_date, benchmark, m0_run, paper_runs, market_data = prepare_replay(
        paths,
        as_of_date,
    )
    result = build_result(
        paths,
        latest_date,
        benchmark,
        m0_run,
        paper_runs,
        market_data,
    )
    return result, m0_run, paper_runs, market_data


def prepare_replay(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    str,
    pd.Series,
    RiskLayerRun,
    dict[str, PaperTradingResult],
    pd.DataFrame,
]:
    """构造V1和增量偏差V2共用的冻结历史撮合输入。"""
    (
        latest_date,
        benchmark,
        m0_run,
        targets,
        market_data,
    ) = prepare_replay_inputs(paths, as_of_date)
    paper_runs = {
        PAPER_BASELINE_ID: _run_paper(
            targets,
            market_data,
            execution_delay=1,
            slippage_bps=10.0,
            participation=0.01,
        ),
        PAPER_STRESS_ID: _run_paper(
            targets,
            market_data,
            execution_delay=2,
            slippage_bps=20.0,
            participation=0.002,
        ),
    }
    return latest_date, benchmark, m0_run, paper_runs, market_data


def prepare_replay_inputs(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    str,
    pd.Series,
    RiskLayerRun,
    dict[str, dict[str, float]],
    pd.DataFrame,
]:
    """构造执行归因研究共用的M0、目标组合和行情。"""
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
        core_targets, _ = quality_support._build_core(
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
    targets = build_core_scoped_sleeve_targets(
        core_targets,
        core_run.exposure,
        core_allocation=0.70,
        defensive_weights=base_study.DEFENSIVE_WEIGHTS,
    )
    targets = {
        date: weights
        for date, weights in targets.items()
        if "20150101" <= date <= latest_date
    }
    bars = pd.concat([stock_bars, fund_panel.bars]).sort_index()
    m0_run = base_study._run_candidate(
        M0_ID,
        targets,
        bars,
        calendar,
        benchmark,
        MixedAssetExecutionModel(
            base_study.FUND_SYMBOLS,
            slippage_bps=5.0,
        ),
        risk_overlay=False,
    )
    market_data = build_paper_market_data(bars)
    return latest_date, benchmark, m0_run, targets, market_data


def build_paper_market_data(bars: pd.DataFrame) -> pd.DataFrame:
    """把统一日线面板转换为Broker使用的股数口径。"""
    frame = bars.reset_index()
    frame = frame[frame["date"] >= pd.Timestamp("2015-01-01")].copy()
    frame["volume"] = (
        pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0) * 100.0
    )
    return frame[
        [
            "date",
            "symbol",
            "open",
            "close",
            "volume",
            "is_suspended",
            "limit_up",
            "limit_down",
        ]
    ].sort_values(["date", "symbol"])


def _run_paper(
    targets: dict[str, dict[str, float]],
    market_data: pd.DataFrame,
    *,
    execution_delay: int,
    slippage_bps: float,
    participation: float,
    open_aware_order_sizing: bool = False,
) -> PaperTradingResult:
    """使用系统Paper Broker执行冻结目标组合。"""
    config = BrokerConfig(
        slippage_bps=slippage_bps,
        execution_delay=execution_delay,
        max_participation_rate=participation,
        commission_rate=0.0003,
        stamp_tax_rate=0.001,
        min_commission=5.0,
        lot_size=100,
        open_aware_order_sizing=open_aware_order_sizing,
        tax_exempt_symbols=frozenset(base_study.FUND_SYMBOLS),
    )
    return PaperTradingEngine(
        initial_cash=INITIAL_CASH,
        broker=BrokerSimulator(config),
    ).run_signals(targets, market_data)


def build_result(
    paths: RuntimePaths,
    latest_date: str,
    benchmark: pd.Series,
    m0_run: RiskLayerRun,
    paper_runs: dict[str, PaperTradingResult],
    market_data: pd.DataFrame,
) -> dict[str, Any]:
    """统一计算收益风险、成交偏差和Paper晋级门槛。"""
    m0_result = slice_result(
        m0_run.result,
        "20150101",
        latest_date,
    )
    m0_metrics = metric_summary(m0_result, benchmark)
    m0_metrics["total_execution_cost"] = float(m0_result.total_cost)
    paper_metrics = {
        scenario_id: paper_metric_summary(
            scenario_id,
            paper_result,
            benchmark,
        )
        for scenario_id, paper_result in paper_runs.items()
    }
    diagnostics = {
        scenario_id: execution_diagnostics(
            paper_result,
            market_data,
            m0_result.daily_values,
            INITIAL_CASH,
        )
        for scenario_id, paper_result in paper_runs.items()
    }
    gate = evaluate_paper_gate(m0_metrics, paper_metrics, diagnostics)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_paper_report(
            m0_metrics,
            paper_metrics,
            diagnostics,
            gate,
            latest_date,
        ),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "m0_metrics": m0_metrics,
        "paper_metrics": paper_metrics,
        "diagnostics": diagnostics,
        "gate": gate,
        "promotion_allowed": False,
        "paper_candidate": bool(gate["passed"]),
        "report_path": str(report_path),
        "reused": False,
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    m0_run: RiskLayerRun,
    paper_runs: dict[str, PaperTradingResult],
    market_data: pd.DataFrame,
) -> None:
    """归档三条净值、成交明细和可执行性报告。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    curves = {
        M0_ID: m0_run.result.daily_values,
        **{
            scenario_id: paper_curve(paper_result)
            for scenario_id, paper_result in paper_runs.items()
        },
    }
    pd.concat(
        [
            (curve / float(curve.iloc[0])).rename(name)
            for name, curve in curves.items()
        ],
        axis=1,
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    executions_path = attempt.output_dir / "paper_executions.csv"
    _execution_frame(paper_runs).to_csv(executions_path, index=False)
    drift_path = attempt.output_dir / "paper_diagnostics.csv"
    pd.DataFrame(
        [
            {"scenario_id": scenario_id, **metrics}
            for scenario_id, metrics in result["diagnostics"].items()
        ]
    ).to_csv(drift_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "历史Paper执行偏差通过冻结门槛，可创建长期观察实例"
            if passed
            else "历史Paper执行偏差超出门槛，不注册Paper"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "Paper可执行性报告"),
            ExperimentArtifact("daily_nav", nav_path, "M0和Paper净值"),
            ExperimentArtifact(
                "paper_executions",
                executions_path,
                "Paper委托成交明细",
            ),
            ExperimentArtifact(
                "paper_diagnostics",
                drift_path,
                "Paper执行偏差指标",
            ),
        ],
    )


def _execution_frame(
    paper_runs: dict[str, PaperTradingResult],
) -> pd.DataFrame:
    """展开全部Paper委托，便于复核拒单和部分成交。"""
    rows = []
    for scenario_id, result in paper_runs.items():
        for order in result.orders:
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "order_id": order.order_id,
                    "signal_date": order.signal_date,
                    "execute_date": order.execute_date,
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": order.quantity,
                    "filled_quantity": order.filled_quantity,
                    "fill_price": order.fill_price,
                    "status": order.status,
                    "reject_reason": order.reject_reason,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
