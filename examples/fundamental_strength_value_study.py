"""基本面强度价值策略的固定样本外研究。"""

from __future__ import annotations

import argparse
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
from examples.quality_factor_study_support import build_period_metrics, metric_summary, slice_result
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.fundamental_strength_value import score_fundamental_strength_value_frame
from factors.quality import score_quality_frame
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
from strategies.quality_universe import apply_quality_universe_filters, load_annual_quality_candidates


STRATEGY_ID = "fundamental_strength_value_v1"
REPORT_PATH = Path("docs/research/fundamental-strength-value-study.md")
TOP_N = 40
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Fundamental Strength Value V1",
    category="factor_strategy",
    hypothesis="离散财务健康度能否过滤点时价值因子的价值陷阱并形成独立低频Alpha",
    definition={
        "strategy": {
            "fundamental_strength": {
                "weight": 0.70,
                "signals": {
                    "positive_roa": "roa>0",
                    "positive_ocf": "ocf_to_or>0",
                    "cash_backed_profit": "ocf_to_profit>1",
                    "positive_profit_growth": "netprofit_yoy>0",
                    "low_leverage": "debt_to_assets<=cross_section_median",
                    "high_margin": "grossprofit_margin>=cross_section_median",
                    "high_asset_turnover": "assets_turn>=cross_section_median",
                },
            },
            "point_in_time_value": {
                "weight": 0.30,
                "factors": ["earnings_yield", "book_yield"],
                "corporate_action_gate": "adj_factor_change<=10pct",
            },
        },
        "diagnostics": {
            "strength_only": {"value_weight": 0.0},
            "value_only": {"value_weight": 1.0},
            "quality_v1_baseline": {"top_n": 20},
        },
        "transform": "flags_then_zscore_and_value_winsorize_1_99_zscore",
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "main_candidate_fixed_before_test": True,
        },
        "methodology_version": "v1",
    },
)


def run_study(paths: RuntimePaths, as_of_date: str, *, force: bool = False) -> dict[str, Any]:
    """先申请研究指纹，再构造数据和运行回测。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """共享一次点时数据准备，主策略和归因对照使用完全一致的交易口径。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0])
        signal_dates = load_month_end_signal_dates(connection)
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        source = apply_quality_universe_filters(
            load_annual_quality_candidates(connection),
            quantile_filter=False,
        )
        source = attach_report_adjustment_factors(connection, source)
        source, audit = build_quality_value_lowvol_candidates(source)
        selections, holdings = _build_selections(source)
        bars = load_feature_bars(
            connection,
            sorted(holdings["symbol"].astype(str).unique().tolist()),
        )
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    benchmark = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    runs = {
        strategy_id: _run_candidate(strategy_id, mapping, bars, calendar, benchmark)
        for strategy_id, mapping in selections.items()
    }
    periods = {
        "train": TRAIN_RANGE,
        "validation": VALIDATION_RANGE,
        "locked_test": (LOCKED_TEST_START, latest_date),
        "full": ("20150101", latest_date),
    }
    metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        benchmark,
        periods,
    )
    annual = _annual_metrics(runs, benchmark, latest_date)
    correlation = _return_correlation(runs[STRATEGY_ID], runs["quality_v1_baseline"])
    gate = evaluate_gate(metrics[STRATEGY_ID], annual[STRATEGY_ID])
    selected = holdings[
        holdings["strategy_id"].eq(STRATEGY_ID)
        & holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(metrics, annual, gate, correlation, latest_date, audit),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "return_correlation_vs_quality": correlation,
        "latest_holdings": selected[
            ["signal_date", "symbol", "name", "rank", "factor_score", "fundamental_strength", "value_score"]
        ].to_dict("records"),
        "corporate_action_audit": {
            "checked_rows": audit.checked_rows,
            "excluded_rows": audit.excluded_rows,
            "missing_rows": audit.missing_rows,
        },
        "report_path": str(output),
        "reused": False,
    }


def _build_selections(source: pd.DataFrame) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame]:
    """主候选研究前固定，强度/价值单腿只用于事后归因而不参与选择。"""
    mappings: dict[str, dict[str, list[str]]] = {}
    selected_frames: list[pd.DataFrame] = []
    variants = {
        "fundamental_strength_only_v1": 0.0,
        "point_in_time_value_only_v1": 1.0,
        STRATEGY_ID: 0.30,
    }
    for strategy_id, value_weight in variants.items():
        scored = _score_by_date(source, value_weight)
        mapping, selected = build_topn_selections(scored, "factor_score", TOP_N)
        selected["strategy_id"] = strategy_id
        mappings[strategy_id] = mapping
        selected_frames.append(selected)

    baseline = _score_quality_by_date(source)
    baseline_mapping, baseline_selected = build_topn_selections(
        baseline,
        "factor_score",
        20,
    )
    baseline_selected["strategy_id"] = "quality_v1_baseline"
    mappings["quality_v1_baseline"] = baseline_mapping
    selected_frames.append(baseline_selected)
    return mappings, pd.concat(selected_frames, ignore_index=True)


def _score_by_date(source: pd.DataFrame, value_weight: float) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        scored = score_fundamental_strength_value_frame(group, value_weight=value_weight)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True)


def _score_quality_by_date(source: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        scored = score_quality_frame(group).rename(columns={"quality_score": "factor_score"})
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True)


def _run_candidate(
    strategy_id: str,
    mapping: dict[str, list[str]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mapping.items()
        if symbols
    }
    return run_risk_layer_backtest(
        strategy_id,
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


def _annual_metrics(
    runs: dict[str, RiskLayerRun],
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, dict[str, float]]]:
    years = range(2015, int(latest_date[:4]) + 1)
    return {
        strategy_id: {
            str(year): metric_summary(
                slice_result(run.result, f"{year}0101", min(f"{year}1231", latest_date)),
                benchmark,
            )
            for year in years
        }
        for strategy_id, run in runs.items()
    }


def _return_correlation(left: RiskLayerRun, right: RiskLayerRun) -> float:
    left_returns = left.result.daily_values.pct_change()
    right_returns = right.result.daily_values.pct_change()
    aligned = pd.concat([left_returns, right_returns], axis=1).dropna()
    return float(aligned.corr().iloc[0, 1]) if len(aligned) > 1 else 0.0


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """固定门槛只判断是否值得进入独立确认，不据此改策略定义。"""
    locked = metrics["locked_test"]
    full = metrics["full"]
    positive_years = sum(item["annualized_return"] > 0 for item in annual.values())
    checks = {
        "locked_test_annual_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_test_sharpe_at_least_055": locked["sharpe"] >= 0.55,
        "locked_test_drawdown_within_30pct": locked["max_drawdown"] >= -0.30,
        "locked_test_positive_excess": locked["excess_return"] > 0,
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_drawdown_within_32pct": full["max_drawdown"] >= -0.32,
        "at_least_nine_positive_years": positive_years >= 9,
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
    }
    return {"passed": all(checks.values()), "checks": checks, "positive_years": positive_years}


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "固定主候选通过样本外与全历史门槛，允许进入独立确认"
            if passed
            else "固定主候选未通过门槛，保留失败指纹且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    correlation: float,
    latest_date: str,
    audit: Any,
) -> str:
    rows: list[str] = []
    for strategy_id, periods in metrics.items():
        for period in ("validation", "locked_test", "full"):
            item = periods[period]
            rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2%} |"
            )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | {item['max_drawdown']:.2%} | "
        f"{item['sharpe']:.3f} |"
        for year, item in annual[STRATEGY_ID].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Fundamental Strength Value V1 Study

- 数据截止：{latest_date}
- 主策略固定：基本面强度70% + 点时E/P、B/P共30%，Top40等权，月频。
- 归因对照：基本面强度单腿、价值单腿和Quality V1，仅解释收益来源，不参与选参。
- 统一口径：年报f_ann_date as-of、公司行动门禁、qfq、M0 T+1、5bps及原风险层。
- 公司行动门禁：检查{audit.checked_rows}条，剔除{audit.excluded_rows}条，缺失{audit.missing_rows}条。
- 与Quality V1日收益相关性：{correlation:.3f}。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 主策略年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        indicator=paths.fina_indicator_path,
        income=paths.income_statement_path,
        balance=paths.balance_sheet_path,
        cashflow=paths.cashflow_statement_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
