"""Fama-French 经营盈利能力独立因子的固定样本外研究。"""

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
from data.operating_profitability import (
    OperatingProfitabilityPaths,
    attach_operating_profitability_databases,
    create_operating_profitability_signal_dates,
    materialize_operating_profitability_asof,
)
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.operating_profitability_feasibility_study import (
    STUDY_START,
    load_candidates,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.operating_profitability import score_operating_profitability_frame
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


STRATEGY_ID = "operating_profitability_v1"
REPORT_PATH = Path("docs/research/operating-profitability-v1.md")
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="经营盈利能力 V1",
    category="factor_strategy",
    hypothesis="扣除经营费用后相对账面权益的盈利能力是否形成稳定独立Alpha",
    definition={
        "academic_definition": {
            "family": "Fama-French_RMW",
            "reference": (
                "https://mba.tuck.dartmouth.edu/pages/Faculty/"
                "ken.French/Data_Library/variable_definitions.html"
            ),
        },
        "factor": {
            "formula": (
                "(revenue-oper_cost-sell_exp-admin_exp-interest_expense)"
                "/total_hldr_eqy_inc_min_int"
            ),
            "interest_expense": "coalesce(fin_exp_int_exp,int_exp,0)",
            "missing_sell_admin_interest": "zero_with_missingness_audit",
            "direction": "higher_is_better",
            "transform": "raw_cross_sectional_percentile_rank",
        },
        "visibility": {
            "annual_report_only": True,
            "each_statement_f_ann_date_lte_signal_date": True,
            "latest_visible_revision": True,
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
            "parameters_fixed_before_test": True,
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
    """先申请固定定义指纹，再运行唯一一次正式回测。"""
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
    """构造点时截面并复用标准风险层和 M0 执行。"""
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
        create_operating_profitability_signal_dates(connection, signal_dates)
        attach_operating_profitability_databases(
            connection,
            OperatingProfitabilityPaths(
                paths.income_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_operating_profitability_asof(connection)
        candidates = load_candidates(connection)
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("经营盈利能力因子没有产生历史持仓")
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
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "operating_profitability",
                "gross_profitability",
                "report_period",
                "publish_date",
                "interest_expense_missing",
            ]
        ].to_dict("records"),
        "report_path": str(report_path),
        "reused": False,
    }


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """逐月生成 Top40 等权目标，不在因子层决定权重。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_operating_profitability_frame(group)
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
    """衡量与毛利润率、动量的重叠以及截止位并列。"""
    gross_correlations: list[float] = []
    gross_overlaps: list[float] = []
    momentum_overlaps: list[float] = []
    cutoff_ties: list[int] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_operating_profitability_frame(group)
        valid = scored.dropna(subset=["gross_profitability", "ret120"])
        if len(valid) < TOP_N:
            continue
        correlation = valid["operating_profitability"].rank().corr(
            valid["gross_profitability"].rank()
        )
        if pd.notna(correlation):
            gross_correlations.append(float(correlation))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        gross_top = set(
            valid.nlargest(TOP_N, "gross_profitability")["symbol"].astype(str)
        )
        momentum_top = set(valid.nlargest(TOP_N, "ret120")["symbol"].astype(str))
        gross_overlaps.append(len(selected & gross_top) / TOP_N)
        momentum_overlaps.append(len(selected & momentum_top) / TOP_N)
        cutoff = valid["operating_profitability"].nlargest(TOP_N).iloc[-1]
        cutoff_ties.append(int(valid["operating_profitability"].eq(cutoff).sum()))
    return {
        "median_spearman_with_gross_profitability": float(
            pd.Series(gross_correlations).median()
        ),
        "median_top40_overlap_with_gross_profitability": float(
            pd.Series(gross_overlaps).median()
        ),
        "median_top40_overlap_with_momentum": float(
            pd.Series(momentum_overlaps).median()
        ),
        "maximum_cutoff_tie_count": float(max(cutoff_ties)),
        "selected_operating_profitability_median": float(
            holdings["operating_profitability"].median()
        ),
        "selected_interest_missing_share": float(
            holdings["interest_expense_missing"].mean()
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档结果；未通过时保留失败指纹并终止该方向。"""
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
            "经营盈利能力通过固定门槛，允许进入独立确认"
            if passed
            else "经营盈利能力未通过固定门槛，终止且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "经营盈利能力研究报告"),
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
    """生成固定样本外研究报告。"""
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
    return f"""# 经营盈利能力 V1

- 数据截止：{latest_date}；仅使用公告日已可见且年龄1至2年的1231年报。
- 因子：营收扣除营业成本、销售/管理/利息费用后除以含少数股东权益。
- 股票池：上市满3年，剔除ST、退市、停牌和成交额最低20%。
- 组合与执行：原始横截面秩、Top40月频等权、qfq、M0 T+1、5bps。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与 Gross Profitability 截面相关/Top40重叠中位数：
  {diagnostics['median_spearman_with_gross_profitability']:.3f} /
  {diagnostics['median_top40_overlap_with_gross_profitability']:.1%}。
- 与动量Top40重叠中位数：
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
- 截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}；
  入选样本利息费用缺失率：
  {diagnostics['selected_interest_missing_share']:.2%}。
- 月度候选数最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。

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


def _data_version(paths: RuntimePaths) -> str:
    """绑定财务、行情和基准相关数据版本。"""
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
