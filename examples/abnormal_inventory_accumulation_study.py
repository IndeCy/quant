"""异常存货积累因子的固定点时回测研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.abnormal_inventory import (
    AbnormalInventoryPaths,
    attach_abnormal_inventory_databases,
    create_abnormal_inventory_signal_dates,
    materialize_abnormal_inventory_asof,
)
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.abnormal_inventory_accumulation_report import render_report
from examples.abnormal_inventory_accumulation_support import (
    MIN_CANDIDATES,
    MIN_COVERAGE,
    MIN_MONTH_SHARE,
    MIN_UNIQUE_VALUES,
    TOP_N,
    build_diagnostics,
    build_monthly_coverage,
    build_targets,
    evaluate_data_gate,
    load_investable_panel,
)
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "abnormal_inventory_accumulation_v1"
REPORT_PATH = Path("docs/research/abnormal-inventory-accumulation-v1.md")
STUDY_START = "20150101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="异常存货积累因子 V1",
    category="factor_strategy",
    hypothesis="存货增长显著快于销售是否预示需求错配和较弱未来收益",
    definition={
        "factor": {
            "formula": "ln(inventory_t/inventory_t_1)-ln(revenue_t/revenue_t_1)",
            "direction": "lower_is_better",
            "transform": "winsorize_1_99_then_cross_sectional_percentile_rank",
            "positive_inputs_required": True,
        },
        "prior_research_distinction": {
            "cash_conversion_cycle": "inventory_vs_sales_growth_not_working_capital_days",
            "low_asset_growth": "inventory_specific_not_total_asset_investment",
            "cash_cow": "demand_mismatch_not_cashflow_efficiency",
        },
        "visibility": {
            "annual_reports_only": True,
            "each_statement_f_ann_date_lte_signal_date": True,
            "latest_visible_revision": True,
            "requires_two_consecutive_annual_statements": True,
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "data_gate": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "coverage_floor": MIN_COVERAGE,
            "qualified_month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "visibility_and_duplicate_violations": 0,
        },
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "parameters_fixed_before_backtest": True,
            "no_follow_up_variants": True,
        },
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记冻结指纹，再读取财务大表和启动回测。"""
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
        result, context = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, context)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """先执行数据门禁，通过后才读取回测价格。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_abnormal_inventory_signal_dates(connection, signal_dates)
        attach_abnormal_inventory_databases(
            connection,
            AbnormalInventoryPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_abnormal_inventory_asof(connection)
        panel = load_investable_panel(connection)
        monthly = build_monthly_coverage(panel)
        data_gate = evaluate_data_gate(connection, monthly)
        if not data_gate["passed"]:
            result = _feasibility_rejection(latest_date, data_gate, monthly)
            _write_report(paths, result)
            return result, {"monthly": monthly, "holdings": pd.DataFrame()}
        candidates = panel.dropna(
            subset=["abnormal_inventory_accumulation"]
        ).copy()
        targets, holdings, counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("异常存货积累因子没有产生历史持仓")
        bars = load_feature_bars(connection, symbols)
        calendar = [
            date
            for date in load_trading_calendar(connection)
            if STUDY_START <= date.strftime("%Y%m%d") <= latest_date
        ]
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    run = run_risk_layer_backtest(
        STRATEGY_ID,
        "GRID",
        targets,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )
    periods = {
        "train": TRAIN_RANGE,
        "validation": VALIDATION_RANGE,
        "locked_test": (LOCKED_TEST_START, latest_date),
        "full": (STUDY_START, latest_date),
    }
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    annual = build_annual_metrics(run, benchmark, latest_date)
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, annual, quality_correlation)
    latest = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ]
    result = {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "decision": "PASSED" if gate["passed"] else "REJECTED",
        "data_gate": data_gate,
        "candidate_counts": counts,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "gate": gate,
        "latest_holdings": records_without_missing(
            latest[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "abnormal_inventory_accumulation",
                    "inventory_log_growth",
                    "revenue_log_growth",
                    "report_period",
                    "publish_date",
                ]
            ]
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    _write_report(paths, result)
    return result, {"monthly": monthly, "holdings": holdings}


def _feasibility_rejection(
    latest_date: str,
    data_gate: dict[str, Any],
    monthly: pd.DataFrame,
) -> dict[str, Any]:
    """构造不触发回测的正式失败结果。"""
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "decision": "REJECTED_BEFORE_BACKTEST",
        "data_gate": data_gate,
        "candidate_counts": {
            "min": float(monthly["candidate_count"].min()),
            "median": float(monthly["candidate_count"].median()),
            "latest": float(monthly["candidate_count"].iloc[-1]),
        },
        "latest_holdings": [],
        "report_path": str(REPORT_PATH),
        "reused": False,
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    context: dict[str, pd.DataFrame],
) -> None:
    """归档覆盖、持仓和失败结论，不注册任何生产实例。"""
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    holdings_path = attempt.output_dir / "holdings.csv"
    context["monthly"].to_csv(monthly_path, index=False)
    context["holdings"].to_csv(holdings_path, index=False)
    decision = str(result["decision"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "PASSED_RESEARCH_GATE"
            if decision == "PASSED"
            else "REJECTED"
        ),
        decision_reason={
            "PASSED": "异常存货积累通过固定门槛，仅进入独立确认",
            "REJECTED": "异常存货积累未通过回测门槛，终止且不注册",
            "REJECTED_BEFORE_BACKTEST": "数据门禁失败，未启动收益回测",
        }[decision],
        artifacts=[
            ExperimentArtifact("summary", summary, "异常存货积累报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖"),
            ExperimentArtifact("holdings", holdings_path, "全部月度持仓"),
        ],
    )


def _write_report(paths: RuntimePaths, result: dict[str, Any]) -> None:
    """写入可读研究报告。"""
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    result["report_path"] = str(output)
    output.write_text(render_report(result), encoding="utf-8")


def records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """将 Pandas 缺失值转换为 JSON null。"""
    return [
        {
            key: None if pd.isna(value) else value
            for key, value in record.items()
        }
        for record in frame.to_dict("records")
    ]


def _data_version(paths: RuntimePaths) -> str:
    """绑定本研究实际消费的源数据版本。"""
    items = [
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("base_market", paths.base_market_path),
        ("market_increment", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
    ]
    return "|".join(
        f"{label}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for label, path in items
    )


def main() -> None:
    """运行命令行研究入口。"""
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
