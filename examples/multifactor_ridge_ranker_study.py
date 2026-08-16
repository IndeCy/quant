"""五个既有因子的固定 Ridge 年度扩展 Walk Forward 研究。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import QualityFinancialPaths
from examples.multifactor_ridge_ranker_artifacts import (
    complete_attempt as _complete_attempt,
)
from examples.multifactor_ridge_ranker_metrics import (
    EQUAL_ID,
    FIRST_TEST_YEAR,
    ML_ID,
    QUALITY_ID,
    average_holding_overlap,
    build_annual_metrics,
    build_failure_attribution,
    evaluate_gate,
    summarize_coefficients,
    summarize_predictions,
)
from examples.multifactor_ridge_ranker_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import (
    RiskLayerRun,
    run_risk_layer_backtest,
)
from ml.contracts import DatasetSpec
from ml.cross_sectional_ridge import run_annual_expanding_ridge
from ml.evaluation import (
    build_prediction_selections,
    build_return_bucket_diagnostics,
)
from ml.multifactor_dataset import build_multifactor_ml_dataset
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchSpec,
    begin_research_attempt,
    fail_research_attempt,
)
from strategies.quality_balanced_value_signal import (
    EXPECTED_WEIGHTS,
    build_quality_balanced_value_topn,
)
from strategies.quality_value_lowvol_signal import (
    build_quality_value_lowvol_topn,
)


EXPERIMENT_ID = "multifactor_ridge_ranker_v1"
REPORT_PATH = Path("docs/research/multifactor-ridge-ranker-v1.md")
FEATURES = (
    "roa",
    "ocf_to_or",
    "earnings_yield",
    "book_yield",
    "low_volatility_60d",
)
TOP_N = 20
DATASET_SPEC = DatasetSpec(
    dataset_id=EXPERIMENT_ID,
    features=FEATURES,
    top_n=TOP_N,
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="多因子固定 Ridge Ranker V1",
    category="machine_learning",
    hypothesis="跨质量价值低波信息族的固定线性学习能否产生稳定样本外增量",
    definition={
        "features": FEATURES,
        "feature_transform": "monthly_winsorize_1_99_zscore",
        "target": "next_month_t1_open_cross_section_rank",
        "model": {
            "type": "ridge",
            "alpha": 1.0,
            "model_selection": "none",
            "parameter_search": "none",
        },
        "walk_forward": {
            "type": "annual_expanding",
            "first_test_year": FIRST_TEST_YEAR,
            "purge_rule": "train_exit_date_before_test_year",
        },
        "universe": "quality_cleanup_with_corporate_action_gate",
        "portfolio": {
            "top_n": TOP_N,
            "weighting": "equal_weight",
            "rebalance": "monthly",
        },
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
        },
        "controls": [EQUAL_ID, QUALITY_ID],
        "evaluation": {
            "periods": ["2019_2021", "2022_2023", "2024_latest", "full_oos"],
            "mean_rank_ic_min": 0.02,
            "positive_ic_month_ratio_min": 0.55,
            "full_annual_return_min": 0.10,
            "full_max_drawdown_floor": -0.30,
            "full_sharpe_min": 0.65,
            "full_calmar_min": 0.30,
            "annual_turnover_max": 8.0,
            "positive_years_min": 6,
            "all_periods_positive": True,
            "median_period_sharpe_min": 0.50,
            "equal_control_sharpe_improvement_min": 0.05,
            "equal_control_return_shortfall_max": 0.02,
            "equal_control_drawdown_deterioration_max": 0.03,
            "equal_control_turnover_multiplier_max": 1.25,
            "quality_sharpe_shortfall_max": 0.05,
            "quality_return_shortfall_max": 0.02,
            "quality_drawdown_deterioration_max": 0.03,
            "quality_return_correlation_max": 0.85,
            "quality_holding_overlap_max": 0.70,
            "stable_positive_features_min": 4,
        },
        "promotion_scope": "research_only",
        "methodology_version": "annual_walk_forward_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记完整计算指纹，再构造大体量点时数据集。"""
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    """构造点时数据、逐年训练并在同一成交口径比较三个组合。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        dataset = build_multifactor_ml_dataset(
            connection,
            _financial_paths(paths),
            spec=DATASET_SPEC,
        )
        walk = run_annual_expanding_ridge(
            dataset.trainable_frame(),
            FEATURES,
            first_test_year=FIRST_TEST_YEAR,
        )
        ml_selections, ml_holdings = build_prediction_selections(
            walk.predictions,
            top_n=TOP_N,
        )
        allowed_dates = set(ml_selections)
        equal_selections, _ = build_quality_value_lowvol_topn(
            dataset.frame,
            {feature: 1.0 / len(FEATURES) for feature in FEATURES},
            top_n=TOP_N,
        )
        quality_selections, _ = build_quality_balanced_value_topn(
            dataset.frame,
            EXPECTED_WEIGHTS,
            top_n=TOP_N,
        )
        mappings = {
            ML_ID: ml_selections,
            EQUAL_ID: _filter_dates(equal_selections, allowed_dates),
            QUALITY_ID: _filter_dates(quality_selections, allowed_dates),
        }
        symbols = sorted(
            {
                symbol
                for mapping in mappings.values()
                for selected in mapping.values()
                for symbol in selected
            }
        )
        bars = load_feature_bars(connection, symbols)
        calendar = [
            date
            for date in load_trading_calendar(connection)
            if date >= pd.Timestamp(f"{FIRST_TEST_YEAR}0101")
        ]
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=as_of_date,
    )
    runs = {
        name: _run(name, mapping, bars, calendar, benchmark)
        for name, mapping in mappings.items()
    }
    latest_date = min(
        run.result.daily_values.index.max() for run in runs.values()
    ).strftime("%Y%m%d")
    periods = {
        "2019_2021": ("20190101", "20211231"),
        "2022_2023": ("20220101", "20231231"),
        "2024_latest": ("20240101", latest_date),
        "full_oos": ("20190101", latest_date),
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual = build_annual_metrics(runs[ML_ID], benchmark, latest_date)
    prediction_metrics = summarize_predictions(walk.predictions)
    coefficients = summarize_coefficients(walk.coefficients)
    quality_correlation = _return_correlation(runs[ML_ID], runs[QUALITY_ID])
    quality_overlap = average_holding_overlap(
        mappings[ML_ID],
        mappings[QUALITY_ID],
    )
    full_comparison = {
        name: values["full_oos"] for name, values in metrics.items()
    }
    bucket = build_return_bucket_diagnostics(walk.predictions)
    failure_attribution = build_failure_attribution(
        bucket,
        coefficients,
        full_comparison,
    )
    gate = evaluate_gate(
        metrics[ML_ID],
        annual,
        prediction_metrics,
        coefficients,
        full_comparison,
        quality_correlation,
        quality_overlap,
    )
    result = {
        "strategy_id": ML_ID,
        "latest_date": latest_date,
        "dataset_manifest": dataset.manifest.to_dict(),
        "corporate_action_audit": dataset.corporate_action_audit.__dict__,
        "prediction_metrics": prediction_metrics,
        "period_metrics": metrics[ML_ID],
        "annual_metrics": annual,
        "full_comparison": full_comparison,
        "coefficient_stability": coefficients,
        "quality_return_correlation": quality_correlation,
        "quality_holding_overlap": quality_overlap,
        "failure_attribution": failure_attribution,
        "gate": gate,
        "latest_holdings": (
            ml_holdings[
                ml_holdings["signal_date"].astype(str).eq(
                    ml_holdings["signal_date"].astype(str).max()
                )
            ].to_dict("records")
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, {
        "dataset": dataset,
        "walk": walk,
        "runs": runs,
        "holdings": ml_holdings,
        "bucket": bucket,
    }


def _run(
    name: str,
    selections: dict[str, list[str]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in selections.items()
        if symbols
    }
    return run_risk_layer_backtest(
        name,
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


def _filter_dates(
    mapping: dict[str, list[str]],
    allowed_dates: set[str],
) -> dict[str, list[str]]:
    return {
        date: symbols
        for date, symbols in mapping.items()
        if date in allowed_dates
    }


def _return_correlation(left: RiskLayerRun, right: RiskLayerRun) -> float:
    return float(
        left.result.daily_values.pct_change().corr(
            right.result.daily_values.pct_change()
        )
    )


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    items = [
        ("base_market", paths.base_market_path),
        ("market_increment", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
        ("fina", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
    ]
    return "|".join(
        f"{label}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        for label, path in items
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_study(
                get_runtime_paths(),
                args.as_of_date,
                force=args.force,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
