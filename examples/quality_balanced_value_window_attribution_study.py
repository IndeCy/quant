"""解释 Quality Balanced Value V1 低 Sharpe 窗口的因子腿来源。"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_balanced_value_window_attribution_metrics import (
    ATTRIBUTION_VARIANTS,
    build_leave_one_out_summary,
    diagnose_drag,
    score_factor_leg_subset,
)
from examples.quality_balanced_value_window_attribution_report import render_report
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


EXPERIMENT_ID = "quality_balanced_value_window_attribution_v1"
REPORT_PATH = Path(
    "docs/research/quality-balanced-value-window-attribution-v1.md"
)
TOP_N = 20
DIAGNOSTIC_WINDOWS: dict[str, tuple[str, str]] = {
    "2016_2018": ("20160101", "20181231"),
    "2017_2019": ("20170101", "20191231"),
    "2018_2020": ("20180101", "20201231"),
    "2020_2022": ("20200101", "20221231"),
    "2022_2024": ("20220101", "20241231"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality Balanced Value 低效窗口因子腿归因",
    category="strategy_attribution",
    hypothesis="低Sharpe窗口来自估值扩展腿拖累、Quality核心拖累或共同市场环境",
    definition={
        "control_strategy": "quality_balanced_value_v1",
        "diagnostic_windows": DIAGNOSTIC_WINDOWS,
        "factor_legs": ATTRIBUTION_VARIANTS,
        "factor_weights": {
            "quality": 0.80,
            "earnings_yield": 0.10,
            "book_yield": 0.10,
        },
        "portfolio": {"top_n": TOP_N, "rebalance": "monthly_equal_weight"},
        "execution": "M0_T1_qfq_5bps",
        "risk_overlay": "GRID_vol20_45_to_30",
        "decision": "diagnostic_only_no_parameter_or_strategy_change",
        "methodology_version": "v1_preregistered",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先固化研究指纹，再读取收益和执行回测。"""
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
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """构造共用候选池，并串行执行七组固定因子腿。"""
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
        signal_dates = load_month_end_signal_dates(connection)
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        source = apply_quality_universe_filters(
            load_annual_quality_candidates(connection)
        )
        source = attach_report_adjustment_factors(connection, source)
        source, audit = build_quality_value_lowvol_candidates(source)
        selections, holdings = _build_selections(source)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    backtest_results: dict[str, Any] = {}
    for variant, mapping in selections.items():
        target_weights = {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in mapping.items()
            if symbols
        }
        run = run_risk_layer_backtest(
            variant,
            "GRID",
            target_weights,
            bars,
            calendar,
            benchmark,
            ExecutionModel(slippage_bps=5.0),
            vol_window=20,
            vol_threshold=0.45,
            reduced_exposure=0.30,
        )
        backtest_results[variant] = run.result

    periods = {
        name: (start, min(end, latest_date))
        for name, (start, end) in DIAGNOSTIC_WINDOWS.items()
    }
    metrics = build_period_metrics(backtest_results, benchmark, periods)
    window_names = list(periods)
    leave_one_out = build_leave_one_out_summary(metrics, window_names)
    diagnosis = diagnose_drag(metrics, window_names, leave_one_out)
    holding_diagnostics = _holding_diagnostics(
        holdings,
        periods,
    )
    result = {
        "latest_date": latest_date,
        "diagnostic_windows": window_names,
        "period_metrics": metrics,
        "leave_one_out": leave_one_out,
        "diagnosis": diagnosis,
        "holding_diagnostics": holding_diagnostics,
        "corporate_action_audit": audit.__dict__,
        "decision": "DIAGNOSTIC_COMPLETE_NO_STRATEGY_CHANGE",
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _build_selections(
    source: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame]:
    """每个变体按月横截面独立评分，但共享完全相同的候选池。"""
    mappings: dict[str, dict[str, list[str]]] = {}
    holdings: list[pd.DataFrame] = []
    for variant, legs in ATTRIBUTION_VARIANTS.items():
        frames: list[pd.DataFrame] = []
        for signal_date, group in source.groupby("signal_date", sort=True):
            scored = score_factor_leg_subset(group, legs)
            scored["signal_date"] = str(signal_date)
            frames.append(scored)
        scored_all = pd.concat(frames, ignore_index=True)
        mapping, selected = build_topn_selections(
            scored_all,
            "factor_score",
            TOP_N,
        )
        selected["variant"] = variant
        mappings[variant] = mapping
        holdings.append(selected)
    return mappings, pd.concat(holdings, ignore_index=True)


def _holding_diagnostics(
    holdings: pd.DataFrame,
    windows: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    """计算持仓重叠与因子暴露，验证因子腿是否真的改变选择。"""
    data = holdings.copy()
    data["signal_date"] = data["signal_date"].astype(str)
    balanced = data[data["variant"].eq("balanced")]
    overlaps: dict[str, dict[str, float]] = {}
    medians: dict[str, dict[str, dict[str, float]]] = {}
    for variant, variant_frame in data.groupby("variant", sort=True):
        overlaps[str(variant)] = {}
        medians[str(variant)] = {}
        for window, (start, end) in windows.items():
            selected = variant_frame[
                variant_frame["signal_date"].between(start, end)
            ]
            control = balanced[balanced["signal_date"].between(start, end)]
            monthly_overlap: list[float] = []
            for signal_date, group in selected.groupby("signal_date", sort=True):
                control_symbols = set(
                    control[control["signal_date"].eq(signal_date)]["symbol"].astype(str)
                )
                symbols = set(group["symbol"].astype(str))
                if symbols:
                    monthly_overlap.append(len(symbols & control_symbols) / len(symbols))
            overlaps[str(variant)][window] = (
                float(pd.Series(monthly_overlap).median())
                if monthly_overlap
                else 0.0
            )
            medians[str(variant)][window] = _feature_medians(selected)
    return {
        "overlap_with_balanced": overlaps,
        "feature_medians": medians,
    }


def _feature_medians(frame: pd.DataFrame) -> dict[str, float]:
    """统一输出选中股票的核心横截面暴露。"""
    if frame.empty:
        return {
            "roa": 0.0,
            "earnings_yield": 0.0,
            "book_yield": 0.0,
            "vol60": 0.0,
            "amount20_yi": 0.0,
        }
    return {
        "roa": float(pd.to_numeric(frame["roa"], errors="coerce").median()),
        "earnings_yield": float(
            pd.to_numeric(frame["earnings_yield"], errors="coerce").median()
        ),
        "book_yield": float(
            pd.to_numeric(frame["book_yield"], errors="coerce").median()
        ),
        "vol60": float(pd.to_numeric(frame["vol60"], errors="coerce").median()),
        # Tushare amount 单位为千元，除以10万后转换为亿元。
        "amount20_yi": float(
            pd.to_numeric(frame["amount20"], errors="coerce").median() / 100_000
        ),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """登记诊断完成，不把任何因子腿标记为生产候选。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            f"低效窗口归因完成：{result['diagnosis']['label']}；"
            "研究不改变现有策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "低效窗口归因报告"),
        ],
    )


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    """返回现有四张财务库，不引入数据源。"""
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定本次归因依赖的全部行情和财务文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
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
