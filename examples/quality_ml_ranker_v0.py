"""Quality ML Ranker V0：固定因子、固定模型、严格样本外研究。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from typing import Any

import pandas as pd

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from data.live_market_view import open_live_market_connection
from data.market_features import load_feature_bars, load_trading_calendar, materialize_market_features
from data.quality_financial import QualityFinancialPaths
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.strategy_comparison_research import (
    BacktestResearchResult,
    build_metrics_table,
)
from ml.dataset import QualityMLDataset, build_quality_ml_dataset
from ml.evaluation import (
    build_prediction_selections,
    build_return_bucket_diagnostics,
    evaluate_promotion_gate,
    select_model_on_validation,
)
from ml.split import DatasetSplits, split_train_validation_test
from ml.trainer import TrainedModel, summarize_prediction_metrics, train_fixed_candidates
from ml.walk_forward import WalkForwardResult, run_annual_expanding_walk_forward
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.ml_experiment_artifacts import write_quality_ml_experiment
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    fail_research_attempt,
)
from strategies.quality_signal import build_quality_topn


EXPERIMENT_ID = "quality_ml_ranker_v0"
VALIDATION_START = "20190101"
TEST_START = "20220101"
VOL_WINDOW = 20
VOL_THRESHOLD = 0.45
REDUCED_EXPOSURE = 0.30
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality ML Ranker V0",
    category="machine_learning",
    hypothesis="固定Quality三因子的非线性交互能否产生稳定的样本外增量",
    definition={
        "base_factors": ["roe", "roa", "ocf_to_or"],
        "new_factors": [],
        "models": ["ridge_v0", "hist_gbdt_v0"],
        "split": {
            "train": "2015-2018",
            "validation": "2019-2021",
            "locked_test": "2022+",
        },
        "selection": {"top_n": 20, "rebalance": "monthly"},
        "risk_overlay": {
            "window": VOL_WINDOW,
            "threshold": VOL_THRESHOLD,
            "reduced_exposure": REDUCED_EXPOSURE,
        },
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq"},
        "methodology_version": "v0",
    },
)


def run_research(
    paths: RuntimePaths,
    *,
    as_of_date: str,
    force: bool = False,
) -> dict[str, Any]:
    """运行完整研究；命中相同研究和数据快照时直接复用。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        return _run_research_calculation(
            paths,
            as_of_date=as_of_date,
            attempt=attempt,
        )
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _run_research_calculation(
    paths: RuntimePaths,
    *,
    as_of_date: str,
    attempt: ResearchAttempt,
) -> dict[str, Any]:
    """执行实际的模型训练、样本外评估和回测。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        dataset = build_quality_ml_dataset(connection, _financial_paths(paths))
        splits = split_train_validation_test(dataset.trainable_frame())
        models = train_fixed_candidates(splits)
        baseline_selections, _ = build_quality_topn(dataset.frame, top_n=dataset.spec.top_n)
        static_selections = {
            model_id: build_prediction_selections(model.predictions, top_n=dataset.spec.top_n)[0]
            for model_id, model in models.items()
        }
        calendar = load_trading_calendar(connection)
        benchmark, benchmark_label = load_hs300_benchmark(
            connection,
            VALIDATION_START,
            str(paths.fund_daily_history_path),
            str(paths.fund_basic_history_path),
        )

        validation_runs = _run_validation_backtests(
            models,
            static_selections,
            calendar,
            benchmark,
            connection,
        )
        validation_metrics = _build_run_metrics(validation_runs, benchmark)
        selection_frame = _build_model_selection_frame(models, validation_metrics)
        selected_model_id = select_model_on_validation(selection_frame)

        # 模型选择完成后才允许打开锁定测试集的年度 Walk Forward 结果。
        walk_forward = run_annual_expanding_walk_forward(
            dataset.trainable_frame(),
            model_id=selected_model_id,
            first_test_year=2022,
        )
        walk_selections, walk_holdings = build_prediction_selections(
            walk_forward.predictions,
            top_n=dataset.spec.top_n,
        )
        backtest_runs = _run_test_backtests(
            models=models,
            selected_model_id=selected_model_id,
            static_selections=static_selections,
            walk_selections=walk_selections,
            baseline_selections=baseline_selections,
            calendar=calendar,
            benchmark=benchmark,
            connection=connection,
        )
    finally:
        connection.close()

    test_runs = {name: _slice_risk_run(run, TEST_START) for name, run in backtest_runs.items()}
    test_metrics = _build_run_metrics(test_runs, benchmark)
    annual_metrics = _build_annual_metrics(test_runs, benchmark)
    prediction_metrics = _build_prediction_metric_frame(models, walk_forward, selected_model_id)
    selected_prediction_metrics = summarize_prediction_metrics(walk_forward.predictions)
    promotion_metrics = _build_promotion_metrics(
        selected_prediction_metrics,
        test_metrics,
        selected_model_id,
    )
    promotion_gate = evaluate_promotion_gate(promotion_metrics)
    bucket_diagnostics = build_return_bucket_diagnostics(walk_forward.predictions)
    curves = _build_curve_frame(test_runs, benchmark)
    return write_quality_ml_experiment(
        paths=paths,
        experiment_id=EXPERIMENT_ID,
        as_of_date=as_of_date,
        dataset=dataset,
        splits=splits,
        models=models,
        selected_model_id=selected_model_id,
        selected_holdings=walk_holdings,
        prediction_metrics=prediction_metrics,
        test_metrics=test_metrics,
        annual_metrics=annual_metrics,
        bucket_diagnostics=bucket_diagnostics,
        walk_forward=walk_forward,
        curves=curves,
        promotion_metrics=promotion_metrics,
        promotion_gate=promotion_gate,
        benchmark_label=benchmark_label,
        attempt=attempt,
    )


def _run_validation_backtests(
    models: dict[str, TrainedModel],
    selections: dict[str, dict[str, list[str]]],
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
    connection: Any,
) -> dict[str, RiskLayerRun]:
    mappings = {
        model_id: _filter_selections(mapping, models[model_id].predictions.query("sample == 'validation'")["signal_date"])
        for model_id, mapping in selections.items()
    }
    symbols = sorted({symbol for mapping in mappings.values() for values in mapping.values() for symbol in values})
    bars = load_feature_bars(connection, symbols)
    validation_calendar = [date for date in calendar if pd.Timestamp(VALIDATION_START) <= date < pd.Timestamp(TEST_START)]
    return {
        model_id: _run_overlay(model_id, mapping, bars, validation_calendar, benchmark)
        for model_id, mapping in mappings.items()
    }


def _run_test_backtests(
    *,
    models: dict[str, TrainedModel],
    selected_model_id: str,
    static_selections: dict[str, dict[str, list[str]]],
    walk_selections: dict[str, list[str]],
    baseline_selections: dict[str, list[str]],
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
    connection: Any,
) -> dict[str, RiskLayerRun]:
    combined: dict[str, dict[str, list[str]]] = {}
    for model_id, mapping in static_selections.items():
        dates = models[model_id].predictions.query("sample in ['validation', 'test']")["signal_date"]
        combined[f"{model_id}_static"] = _filter_selections(mapping, dates)
    selected_validation = static_selections[selected_model_id]
    validation_dates = models[selected_model_id].predictions.query("sample == 'validation'")["signal_date"]
    combined[f"{selected_model_id}_walk_forward"] = {
        **_filter_selections(selected_validation, validation_dates),
        **walk_selections,
    }
    common_dates = set(combined[f"{selected_model_id}_walk_forward"])
    combined["quality_v1"] = {
        date: symbols for date, symbols in baseline_selections.items() if date in common_dates
    }
    symbols = sorted({symbol for mapping in combined.values() for values in mapping.values() for symbol in values})
    bars = load_feature_bars(connection, symbols)
    run_calendar = [date for date in calendar if date >= pd.Timestamp(VALIDATION_START)]
    return {
        name: _run_overlay(name, mapping, bars, run_calendar, benchmark)
        for name, mapping in combined.items()
    }


def _run_overlay(
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
        vol_window=VOL_WINDOW,
        vol_threshold=VOL_THRESHOLD,
        reduced_exposure=REDUCED_EXPOSURE,
    )


def _slice_risk_run(run: RiskLayerRun, start_date: str) -> RiskLayerRun:
    start = pd.Timestamp(start_date)
    result = run.result
    trades = [trade for trade in result.trades if pd.Timestamp(trade["date"]) >= start]
    failed = [order for order in result.failed_orders if pd.Timestamp(order["date"]) >= start]
    sliced = BacktestResearchResult(
        strategy=result.strategy,
        daily_values=result.daily_values.loc[start:].copy(),
        trades=trades,
        failed_orders=failed,
        total_cost=float(sum(float(trade.get("fee", 0.0)) for trade in trades)),
        turnover_notional=float(sum(abs(float(trade["quantity"]) * float(trade["price"])) for trade in trades)),
    )
    return RiskLayerRun(sliced, run.exposure.loc[start:].copy(), run.events[run.events["date"] >= start].copy())


def _build_run_metrics(runs: dict[str, RiskLayerRun], benchmark: pd.Series) -> pd.DataFrame:
    metrics = build_metrics_table({name: run.result for name, run in runs.items()}, benchmark)
    metrics["平均仓位"] = metrics["策略"].map(
        {name: float(run.exposure.mean()) if not run.exposure.empty else 0.0 for name, run in runs.items()}
    )
    metrics["Calmar"] = metrics.apply(
        lambda row: float(row["年化收益"] / abs(row["最大回撤"])) if row["最大回撤"] < 0 else 0.0,
        axis=1,
    )
    return metrics


def _build_model_selection_frame(
    models: dict[str, TrainedModel],
    validation_metrics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    indexed = validation_metrics.set_index("策略")
    for model_id, model in models.items():
        row = indexed.loc[model_id]
        rows.append(
            {
                "model_id": model_id,
                "validation_mean_rank_ic": model.metrics["validation_mean_rank_ic"],
                "validation_sharpe": float(row["夏普比率"]),
                "validation_max_drawdown": float(row["最大回撤"]),
                "validation_turnover": float(row["年化换手率"]),
            }
        )
    return pd.DataFrame(rows)


def _build_prediction_metric_frame(
    models: dict[str, TrainedModel],
    walk_forward: WalkForwardResult,
    selected_model_id: str,
) -> pd.DataFrame:
    rows = [{"model_id": model_id, **model.metrics} for model_id, model in models.items()]
    walk_metrics = summarize_prediction_metrics(walk_forward.predictions)
    rows.append({"model_id": f"{selected_model_id}_walk_forward", **walk_metrics})
    return pd.DataFrame(rows)


def _build_promotion_metrics(
    prediction_metrics: dict[str, float],
    backtest_metrics: pd.DataFrame,
    selected_model_id: str,
) -> dict[str, float]:
    indexed = backtest_metrics.set_index("策略")
    selected = indexed.loc[f"{selected_model_id}_walk_forward"]
    baseline = indexed.loc["quality_v1"]
    return {
        "test_mean_rank_ic": prediction_metrics["walk_forward_test_mean_rank_ic"],
        "test_positive_ic_ratio": prediction_metrics["walk_forward_test_positive_ic_ratio"],
        "test_sharpe": float(selected["夏普比率"]),
        "baseline_test_sharpe": float(baseline["夏普比率"]),
        "test_max_drawdown": float(selected["最大回撤"]),
        "baseline_test_max_drawdown": float(baseline["最大回撤"]),
        "test_turnover": float(selected["年化换手率"]),
        "baseline_test_turnover": float(baseline["年化换手率"]),
    }


def _build_annual_metrics(runs: dict[str, RiskLayerRun], benchmark: pd.Series) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, run in runs.items():
        for year, values in run.result.daily_values.groupby(run.result.daily_values.index.year):
            if len(values) < 2:
                continue
            annual_return = float(values.iloc[-1] / values.iloc[0] - 1)
            drawdown = float((values / values.cummax() - 1).min())
            benchmark_values = benchmark.reindex(values.index).ffill().dropna()
            benchmark_return = (
                float(benchmark_values.iloc[-1] / benchmark_values.iloc[0] - 1)
                if len(benchmark_values) >= 2 else 0.0
            )
            rows.append(
                {
                    "策略": name,
                    "年份": int(year),
                    "年度收益": annual_return,
                    "年度最大回撤": drawdown,
                    "年度超额收益": annual_return - benchmark_return,
                }
            )
    return pd.DataFrame(rows)


def _build_curve_frame(runs: dict[str, RiskLayerRun], benchmark: pd.Series) -> pd.DataFrame:
    curves: dict[str, pd.Series] = {}
    for name, run in runs.items():
        values = run.result.daily_values
        curves[name] = values / values.iloc[0] if not values.empty else values
    if curves:
        index = sorted(set().union(*(series.index for series in curves.values())))
    else:
        index = []
    result = pd.DataFrame(index=pd.DatetimeIndex(index))
    for name, series in curves.items():
        result[name] = series.reindex(result.index).ffill()
    aligned = benchmark.reindex(result.index).ffill().dropna()
    if not aligned.empty:
        result["510300"] = aligned / aligned.iloc[0]
    return result.rename_axis("trade_date").reset_index()


def _filter_selections(
    selections: dict[str, list[str]],
    dates: pd.Series,
) -> dict[str, list[str]]:
    allowed = set(dates.astype(str))
    return {date: symbols for date, symbols in selections.items() if date in allowed}


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true", help="显式允许相同数据口径重新计算")
    args = parser.parse_args()
    result = run_research(
        get_runtime_paths(),
        as_of_date=args.as_of_date,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
