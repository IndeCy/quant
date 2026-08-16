"""Quality + Low Beta 固定假设研究。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

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
from data.rolling_beta import attach_rolling_beta
from examples.quality_risk_layer_research import run_risk_layer_backtest
from examples.strategy_comparison_research import build_annual_returns, build_metrics_table
from factors.quality_lowbeta import score_quality_lowbeta_frame
from portfolio.topn import build_topn_selections
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import apply_quality_universe_filters, load_annual_quality_candidates


REPORT_PATH = Path("docs/research/quality-lowbeta-study.md")
STRATEGY_NAME = "Quality LowBeta V0"
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id="quality_lowbeta_v0",
    name=STRATEGY_NAME,
    category="factor_strategy",
    hypothesis="低Beta与低波动能否在不改变Quality股票池的前提下改善回撤",
    definition={
        "factors": {
            "roa": 0.25,
            "ocf_to_or": 0.25,
            "low_beta_120d": 0.25,
            "low_volatility_60d": 0.25,
        },
        "transform": "winsorize_1_99_then_zscore",
        "universe": "quality_cleanup",
        "portfolio": {"top_n": TOP_N, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "methodology_version": "v0",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """执行固定版本；相同数据和研究口径默认复用历史结果。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _run_study_calculation(paths, as_of_date)
        summary_path = attempt.output_dir / "summary.md"
        summary_path.write_text(
            Path(result["report_path"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        registration = complete_research_attempt(
            attempt,
            metrics=result,
            outcome="PASSED" if result["gate"]["passed"] else "REJECTED",
            decision_reason=(
                "通过固定晋级门槛"
                if result["gate"]["passed"]
                else "固定晋级门槛全部未通过，不注册生产策略"
            ),
            artifacts=[ExperimentArtifact("summary", summary_path, "研究报告")],
        )
        return {**result, **registration}
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _run_study_calculation(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """执行唯一固定版本的因子、组合和回测计算。"""
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
        benchmark = load_adjusted_fund_curve(
            paths.fund_daily_history_path,
            paths.benchmark_increment_path,
            "510300.SH",
            end_date=latest_date,
        )
        candidates = apply_quality_universe_filters(load_annual_quality_candidates(connection))
        candidates = attach_rolling_beta(connection, candidates, benchmark)
        candidates["low_beta_120d"] = -pd.to_numeric(candidates["beta_120d"], errors="coerce")
        candidates["low_volatility_60d"] = -pd.to_numeric(candidates["vol60"], errors="coerce")
        scores = _score_by_date(candidates)
        selections, holdings = build_topn_selections(scores, "factor_score", TOP_N)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in selections.items()
        if symbols
    }
    run = run_risk_layer_backtest(
        STRATEGY_NAME,
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
    metrics = build_metrics_table({STRATEGY_NAME: run.result}, benchmark).iloc[0]
    annual = build_annual_returns({STRATEGY_NAME: run.result})
    summary = _summary(metrics, run, holdings)
    gate = evaluate_gate(summary)
    report = render_report(summary, annual, gate)
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    return {
        "summary": summary,
        "gate": gate,
        "annual": annual.to_dict("records"),
        "latest_holdings": holdings[holdings["signal_date"].eq(max(selections))][
            ["symbol", "name", "rank", "factor_score", "beta_120d", "vol60"]
        ].to_dict("records"),
        "report_path": str(output),
    }


def evaluate_gate(summary: dict[str, float]) -> dict[str, Any]:
    """研究前固定的绝对风险收益门槛。"""
    checks = {
        "annualized_return_at_least_10pct": summary["annualized_return"] >= 0.10,
        "max_drawdown_within_25pct": summary["max_drawdown"] >= -0.25,
        "sharpe_at_least_065": summary["sharpe"] >= 0.65,
        "calmar_at_least_045": summary["calmar"] >= 0.45,
        "positive_excess_return": summary["excess_return"] > 0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def render_report(summary: dict[str, float], annual: pd.DataFrame, gate: dict[str, Any]) -> str:
    """生成研究报告，不注册生产策略。"""
    annual_rows = "\n".join(
        f"| {int(row['年份'])} | {float(row['年度收益']):.2%} |"
        for _, row in annual.iterrows()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality LowBeta Study

## 固定定义

- 因子：ROA、OCF_TO_OR、120日低Beta、60日低波，1%/99%缩尾后Z-score等权。
- 股票池：Quality Cleanup，Top40等权，月频调仓。
- 风险层：20日组合波动率大于45%时降至30%，否则100%。
- 执行：qfq、M0 ExecutionModel、T+1、5bps滑点。

## 全历史结果

| 年化收益 | 最大回撤 | Sharpe | Calmar | 总收益 | 超额收益 | 年化换手率 |
|---:|---:|---:|---:|---:|---:|---:|
| {summary['annualized_return']:.2%} | {summary['max_drawdown']:.2%} | {summary['sharpe']:.3f} | {summary['calmar']:.3f} | {summary['total_return']:.2%} | {summary['excess_return']:.2%} | {summary['annual_turnover']:.2%} |

## 年度收益

| 年份 | 收益 |
|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入下一轮稳定性验收' if gate['passed'] else '终止，不注册生产策略'}。
"""


def _score_by_date(candidates: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_lowbeta_frame(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True) if frames else candidates.iloc[0:0].copy()


def _summary(metrics: pd.Series, run: Any, holdings: pd.DataFrame) -> dict[str, float]:
    annualized = float(metrics["年化收益"])
    drawdown = float(metrics["最大回撤"])
    selected = holdings.groupby("signal_date").head(TOP_N)
    return {
        "annualized_return": annualized,
        "max_drawdown": drawdown,
        "sharpe": float(metrics["夏普比率"]),
        "calmar": annualized / abs(drawdown) if drawdown < 0 else 0.0,
        "total_return": float(metrics["总收益"]),
        "excess_return": float(metrics["超额收益"]),
        "annual_turnover": float(metrics["年化换手率"]),
        "execution_cost": float(run.result.total_cost),
        "failed_orders": float(len(run.result.failed_orders)),
        "average_selected_beta": float(selected["beta_120d"].mean()),
    }


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true", help="显式允许相同数据口径重新计算")
    args = parser.parse_args()
    result = run_study(get_runtime_paths(), args.as_of_date, force=args.force)
    print(result["summary"])
    print(result["gate"])


if __name__ == "__main__":
    main()
