"""连续年报资产周转率改善的固定多阶段回测。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.asset_turnover_change import (
    AssetTurnoverFinancialPaths,
    attach_asset_turnover_databases,
    create_asset_turnover_signal_dates,
    materialize_asset_turnover_change_asof,
)
from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.asset_turnover_change_feasibility_study import (
    STUDY_START,
    load_candidates,
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
from factors.asset_turnover_change import score_asset_turnover_change_frame
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


STRATEGY_ID = "asset_turnover_change_v1"
REPORT_PATH = Path("docs/research/asset-turnover-change-v1.md")
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="资产周转率改善 V1",
    category="factor_strategy",
    hypothesis="连续年报资产周转效率改善能否形成稳定且独立的A股Alpha",
    definition={
        "factor": {
            "formula": (
                "revenue_t/avg(total_assets_t,total_assets_t_minus_1)-"
                "revenue_t_minus_1/avg(total_assets_t_minus_1,"
                "total_assets_t_minus_2)"
            ),
            "direction": "higher_is_better",
            "transform": "raw_cross_sectional_percentile_rank",
            "level_or_quality_gate": False,
        },
        "prior_research_distinction": {
            "piotroski": "continuous_single_factor_not_binary_nine_flag_score",
            "quality_margin_efficiency": "annual_change_not_level_or_multifactor",
        },
        "visibility": {
            "annual_reports_only": True,
            "each_statement_f_ann_date_lte_signal_date": True,
            "latest_visible_revision": True,
            "requires_three_consecutive_balance_sheets": True,
            "report_freshness_years": [1, 2],
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
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
        "feasibility_dependency": "asset_turnover_change_data_feasibility_v1",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记冻结定义指纹，再加载数据执行回测。"""
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
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """构造点时截面并复用固定风险层和 M0 执行。"""
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
        create_asset_turnover_signal_dates(connection, signal_dates)
        attach_asset_turnover_databases(
            connection,
            AssetTurnoverFinancialPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_asset_turnover_change_asof(connection)
        candidates = load_candidates(connection)
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("资产周转率改善没有产生历史持仓")
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
    latest_holdings = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            annual,
            gate,
            quality_correlation,
            diagnostics,
            candidate_counts,
            latest_date,
        ),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "quality_return_correlation": quality_correlation,
        "diagnostics": diagnostics,
        "candidate_counts": candidate_counts,
        "latest_holdings": records_without_missing(
            latest_holdings[
                [
                    "signal_date",
                    "symbol",
                    "name",
                    "rank",
                    "factor_score",
                    "asset_turnover_change",
                    "asset_turnover",
                    "prior_asset_turnover",
                    "report_period",
                    "publish_date",
                ]
            ]
        ),
        "report_path": str(report_path),
        "reused": False,
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月选取资产周转率改善 Top40 并生成等权目标。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_asset_turnover_change_frame(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    scores = pd.concat(frames, ignore_index=True)
    mappings, holdings = build_topn_selections(scores, "factor_score", TOP_N)
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mappings.items()
    }
    values = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(values.min()),
        "median": float(values.median()),
        "latest": float(values.iloc[-1]),
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """衡量水平值、动量暴露和截止位并列。"""
    level_correlations: list[float] = []
    momentum_correlations: list[float] = []
    level_overlaps: list[float] = []
    momentum_overlaps: list[float] = []
    cutoff_ties: list[int] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=["asset_turnover_change", "asset_turnover", "ret120"]
        )
        if len(valid) < TOP_N:
            continue
        level_correlations.append(
            float(
                valid["asset_turnover_change"].rank().corr(
                    valid["asset_turnover"].rank()
                )
            )
        )
        momentum_correlations.append(
            float(
                valid["asset_turnover_change"].rank().corr(
                    valid["ret120"].rank()
                )
            )
        )
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        high_level = set(
            valid.nlargest(TOP_N, "asset_turnover")["symbol"].astype(str)
        )
        high_momentum = set(
            valid.nlargest(TOP_N, "ret120")["symbol"].astype(str)
        )
        level_overlaps.append(len(selected & high_level) / TOP_N)
        momentum_overlaps.append(len(selected & high_momentum) / TOP_N)
        cutoff = valid["asset_turnover_change"].nlargest(TOP_N).iloc[-1]
        cutoff_ties.append(int(valid["asset_turnover_change"].eq(cutoff).sum()))
    return {
        "median_spearman_with_turnover_level": _median(level_correlations),
        "median_spearman_with_ret120": _median(momentum_correlations),
        "median_top40_overlap_with_turnover_level": _median(level_overlaps),
        "median_top40_overlap_with_momentum": _median(momentum_overlaps),
        "maximum_cutoff_tie_count": float(max(cutoff_ties)),
        "selected_change_median": float(
            holdings["asset_turnover_change"].median()
        ),
    }


def records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """将研究产物中的缺失值转为 JSON null。"""
    return [
        {
            key: None if pd.isna(value) else value
            for key, value in record.items()
        }
        for record in frame.to_dict("records")
    ]


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档报告与持仓；失败时不注册生产策略。"""
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
            "资产周转率改善通过固定门槛，允许进入独立确认"
            if passed
            else "资产周转率改善未通过固定门槛，终止且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "资产周转率改善报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    diagnostics: dict[str, float],
    candidate_counts: dict[str, float],
    latest_date: str,
) -> str:
    """生成冻结口径的研究报告。"""
    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in metrics.items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in annual.items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# 资产周转率改善 V1

- 数据截止：{latest_date}；连续三年、信号日前可见且年龄1至2年的年报。
- 因子：本年资产周转率减上年资产周转率，原始横截面秩，越高越好。
- 组合与执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 月度候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与周转率水平/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_turnover_level']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与水平值/动量 Top40 重合中位数：
  {diagnostics['median_top40_overlap_with_turnover_level']:.1%} /
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
- 截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}；
  入选变化值中位数：{diagnostics['selected_change_median']:.4f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")


def _data_version(paths: RuntimePaths) -> str:
    """绑定财务、行情和增量快照版本。"""
    parts: list[str] = []
    for label, path in [
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]:
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
