"""Gross Profitability 独立因子的固定样本外研究。"""

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
from factors.gross_profitability import score_gross_profitability_frame
from portfolio.topn import select_topn
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import load_annual_quality_candidates


STRATEGY_ID = "gross_profitability_v1"
REPORT_PATH = Path("docs/research/gross-profitability-v1.md")
STUDY_START = "20150101"
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Gross Profitability V1",
    category="factor_strategy",
    hypothesis="毛利润相对平均总资产的盈利能力是否形成稳定独立Alpha",
    definition={
        "field_semantic_audit": {
            "vendor_formula": "grossprofit_margin*assets_turn",
            "raw_formula": "(annual_revenue-oper_cost)/average_total_assets*100",
            "matched_rows": 78120,
            "correlation": 0.986161,
            "median_absolute_error_pct_point": 0.000594,
            "within_5_pct_point_ratio": 0.999616,
        },
        "factor": {
            "formula": "grossprofit_margin_pct*assets_turn",
            "direction": "higher_is_better",
            "transform": "winsorize_1_99_then_cross_sectional_percentile_rank",
        },
        "visibility": {
            "annual_report_only": True,
            "f_ann_date_lte_signal_date": True,
            "latest_visible_annual_report": True,
        },
        "universe": {
            "roa_or_ocf_required": False,
            "quality_quantile_filter": False,
            "rules": "all_a_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        },
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "parameters_fixed_before_test": True,
            "roa_overlap_is_attribution_only": True,
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
    """先申请固定指纹，再读取财务和行情大表。"""
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
    """构造点时盈利能力截面并运行统一 M0 回测。"""
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
            date
            for date in load_month_end_signal_dates(connection)
            if STUDY_START <= date <= latest_date
        ]
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        candidates = apply_gross_profitability_universe(
            load_annual_quality_candidates(connection)
        )
        targets, holdings, candidate_counts = build_targets(
            candidates,
            signal_dates,
        )
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("Gross Profitability 因子没有产生历史持仓")
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
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
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
                "end_date",
                "f_ann_date",
                "grossprofit_margin",
                "assets_turn",
                "gross_profitability",
                "roa",
                "ret120",
            ]
        ].to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }


def apply_gross_profitability_universe(frame: pd.DataFrame) -> pd.DataFrame:
    """应用可交易过滤，不要求ROA、OCF或Quality分位数。"""
    required = [
        "signal_date",
        "symbol",
        "name",
        "list_date",
        "delist_date",
        "st_name",
        "end_date",
        "f_ann_date",
        "grossprofit_margin",
        "assets_turn",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"gross profitability candidates missing columns: {missing}")
    data = frame.copy()
    signal_date = pd.to_datetime(data["signal_date"], format="%Y%m%d")
    list_date = pd.to_datetime(data["list_date"], format="%Y%m%d", errors="coerce")
    delist_date = pd.to_datetime(
        data["delist_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    listed_years = (signal_date - list_date).dt.days / 365.25
    valid = (
        listed_years.ge(3)
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~(delist_date.notna() & delist_date.le(signal_date))
        & data["end_date"].astype(str).str.endswith("1231")
        & data[["grossprofit_margin", "assets_turn"]].notna().all(axis=1)
        & data["f_ann_date"].astype(str).le(data["signal_date"].astype(str))
    )
    return data[valid].copy()


def build_targets(
    candidates: pd.DataFrame,
    signal_dates: list[str],
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """按月选择Top40 Gross Profitability股票并生成等权目标。"""
    targets: dict[str, dict[str, float]] = {}
    holdings: list[pd.DataFrame] = []
    counts: list[int] = []
    for signal_date in signal_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        scored = score_gross_profitability_frame(group)
        counts.append(len(scored))
        selected = select_topn(scored, "factor_score", TOP_N)
        selected["signal_date"] = signal_date
        symbols = selected["symbol"].astype(str).tolist()
        targets[signal_date] = (
            {symbol: 1.0 / len(symbols) for symbol in symbols} if symbols else {}
        )
        if not selected.empty:
            holdings.append(selected)
    combined = (
        pd.concat(holdings, ignore_index=True)
        if holdings
        else candidates.iloc[0:0].assign(
            factor_score=pd.Series(dtype=float),
            rank=pd.Series(dtype=int),
        )
    )
    values = pd.Series(counts, dtype=float)
    return targets, combined, {
        "min": float(values.min()) if not values.empty else 0.0,
        "median": float(values.median()) if not values.empty else 0.0,
        "latest": float(values.iloc[-1]) if not values.empty else 0.0,
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """衡量Gross Profitability与ROA和动量的重叠。"""
    roa_correlations: list[float] = []
    roa_overlaps: list[float] = []
    momentum_overlaps: list[float] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_gross_profitability_frame(group)
        valid = scored.dropna(subset=["roa", "ret120"])
        if len(valid) < TOP_N:
            continue
        correlation = valid["gross_profitability"].rank().corr(valid["roa"].rank())
        if pd.notna(correlation):
            roa_correlations.append(float(correlation))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        roa_top = set(valid.nlargest(TOP_N, "roa")["symbol"].astype(str))
        momentum_top = set(valid.nlargest(TOP_N, "ret120")["symbol"].astype(str))
        roa_overlaps.append(len(selected & roa_top) / TOP_N)
        momentum_overlaps.append(len(selected & momentum_top) / TOP_N)
    return {
        "median_spearman_with_roa": (
            float(pd.Series(roa_correlations).median())
            if roa_correlations
            else float("nan")
        ),
        "median_top40_overlap_with_roa": (
            float(pd.Series(roa_overlaps).median()) if roa_overlaps else float("nan")
        ),
        "median_top40_overlap_with_momentum": (
            float(pd.Series(momentum_overlaps).median())
            if momentum_overlaps
            else float("nan")
        ),
        "selected_gross_profitability_median": float(
            pd.to_numeric(
                holdings["grossprofit_margin"],
                errors="coerce",
            ).mul(
                pd.to_numeric(holdings["assets_turn"], errors="coerce")
            ).median()
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档研究报告和持仓，不通过时禁止注册。"""
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
            "Gross Profitability通过固定样本外门槛，允许进入独立确认"
            if passed
            else "Gross Profitability未通过固定门槛，保留失败指纹且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
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
    """生成Gross Profitability研究报告。"""
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
    return f"""# Gross Profitability V1

- 数据截止：{latest_date}；只使用已披露的1231年报。
- 因子：毛利率×总资产周转率，近似毛利润/平均总资产，越高越好。
- 原始报表复算相关性0.9862，误差中位数0.0006个百分点。
- 股票池不要求ROA或OCF，不使用Quality分位过滤。
- 执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 与 Quality Balanced Value 日收益相关性：{quality_correlation:.3f}。
- 与ROA截面Spearman中位数：
  {diagnostics['median_spearman_with_roa']:.3f}；Top40重叠
  {diagnostics['median_top40_overlap_with_roa']:.1%}。
- 与动量Top40重叠中位数：
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
- 历史持仓Gross Profitability中位数：
  {diagnostics['selected_gross_profitability_median']:.2f}%。
- 月度候选数：最少 {candidate_counts['min']:.0f}，中位数
  {candidate_counts['median']:.0f}，最新 {candidate_counts['latest']:.0f}。

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


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        indicator=paths.fina_indicator_path,
        income=paths.income_statement_path,
        balance=paths.balance_sheet_path,
        cashflow=paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定财务和行情数据版本。"""
    parts = []
    for label, path in [
        ("fina", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
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
