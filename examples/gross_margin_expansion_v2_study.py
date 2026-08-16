"""毛利率改善 V1 的唯一数据时效与排序语义修正版。"""

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
from data.gross_margin_change import (
    GrossMarginFinancialPaths,
    attach_gross_margin_financial_database,
    create_gross_margin_signal_date_table,
    materialize_gross_margin_change_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.gross_margin_expansion_study import (
    TOP_N,
    _data_version,
    build_diagnostics,
    load_candidates,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.gross_margin_expansion import (
    score_gross_margin_expansion_rank_frame,
)
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


STRATEGY_ID = "gross_margin_expansion_fresh_rank_v2"
REPORT_PATH = Path("docs/research/gross-margin-expansion-fresh-rank-v2.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="毛利率改善新鲜原始秩 V2",
    category="factor_strategy",
    hypothesis="修复陈旧财报和顶部并列后，毛利率改善是否仍具有跨阶段Alpha",
    definition={
        "correction_from": "gross_margin_expansion_v1",
        "corrections": {
            "report_freshness": "signal_year-report_year in [1,2]",
            "ranking": "raw_cross_sectional_percentile_without_winsorization",
        },
        "factor": {
            "formula": "current_annual_gross_margin-prior_annual_gross_margin",
            "direction": "higher_is_better",
        },
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "unchanged": [
            "annual_reports_only",
            "f_ann_date_asof",
            "latest_visible_revision",
            "consecutive_years",
            "standard_universe",
            "Top40_monthly_equal_weight",
            "M0_T_plus_1_qfq_5bps",
            "vol20_45pct_to_30pct",
            "train_validation_locked_test",
        ],
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "no_further_variants": True,
        },
        "methodology_version": "v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """为语义修正版登记独立指纹后再执行计算。"""
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
    """应用两项语义修正并执行唯一一次 V2 M0 回测。"""
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
        create_gross_margin_signal_date_table(connection, signal_dates)
        attach_gross_margin_financial_database(
            connection,
            GrossMarginFinancialPaths(paths.income_statement_path),
        )
        materialize_gross_margin_change_asof(connection)
        candidates = apply_report_freshness(load_candidates(connection))
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_diagnostics(candidates, holdings)
        tie_diagnostics = build_tie_diagnostics(candidates)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("毛利率改善V2没有产生历史持仓")
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
        "full": ("20150101", latest_date),
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
            tie_diagnostics,
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
        "tie_diagnostics": tie_diagnostics,
        "candidate_counts": candidate_counts,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "gross_margin_change",
                "gross_margin",
                "prior_gross_margin",
                "report_period",
                "publish_date",
            ]
        ].to_dict("records"),
        "report_path": str(report_path),
        "reused": False,
    }


def apply_report_freshness(candidates: pd.DataFrame) -> pd.DataFrame:
    """只保留信号年前1至2年的最新年报，排除长期陈旧财务值。"""
    data = candidates.copy()
    signal_year = pd.to_numeric(
        data["signal_date"].astype(str).str[:4],
        errors="coerce",
    )
    report_year = pd.to_numeric(
        data["report_period"].astype(str).str[:4],
        errors="coerce",
    )
    data["report_age_years"] = signal_year - report_year
    return data[data["report_age_years"].between(1, 2, inclusive="both")].copy()


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """使用无截尾原始秩生成 Top40 等权目标。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_gross_margin_expansion_rank_frame(group)
        scored["signal_date"] = str(signal_date)
        counts[str(signal_date)] = len(scored)
        if len(scored) >= TOP_N:
            frames.append(scored)
    if not frames:
        empty = candidates.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
        return {}, empty, {"min": 0.0, "median": 0.0, "latest": 0.0}
    scores = pd.concat(frames, ignore_index=True)
    mapping, holdings = build_topn_selections(scores, "factor_score", TOP_N)
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mapping.items()
    }
    count_series = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(count_series.min()),
        "median": float(count_series.median()),
        "latest": float(count_series.iloc[-1]),
    }


def build_tie_diagnostics(candidates: pd.DataFrame) -> dict[str, float]:
    """确认Top40截止位没有因预处理形成大面积并列。"""
    counts: list[int] = []
    for _, group in candidates.groupby("signal_date", sort=True):
        values = group["gross_margin_change"].dropna().sort_values(ascending=False)
        if len(values) < TOP_N:
            continue
        cutoff = float(values.iloc[TOP_N - 1])
        counts.append(int(values.eq(cutoff).sum()))
    return {
        "median_cutoff_tie_count": (
            float(pd.Series(counts).median()) if counts else float("nan")
        ),
        "maximum_cutoff_tie_count": (
            float(max(counts)) if counts else float("nan")
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档唯一修正版，此后终止毛利率改善参数变体。"""
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
            "毛利率改善V2通过固定门槛，允许进入独立确认"
            if passed
            else "毛利率改善V2仍未通过门槛，终止该方向"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "V2研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    diagnostics: dict[str, float],
    tie_diagnostics: dict[str, float],
    candidate_counts: dict[str, float],
    latest_date: str,
) -> str:
    """生成毛利率改善唯一修正版报告。"""
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
    return f"""# 毛利率改善新鲜原始秩 V2

- 数据截止：{latest_date}。
- 修正：财报年龄仅1至2年；单因子直接按原始变化幅度排名。
- 其余口径保持V1不变：Top40月频、qfq、M0 T+1、5bps及风险层。
- Top40截止位并列中位/最大：
  {tie_diagnostics['median_cutoff_tie_count']:.0f} /
  {tie_diagnostics['maximum_cutoff_tie_count']:.0f}。
- 候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与Quality收益相关性：{quality_correlation:.3f}。
- 与毛利率水平/120日动量Spearman中位数：
  {diagnostics['median_spearman_with_margin_level']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止毛利率改善方向'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
