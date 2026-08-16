"""季度公告漂移Top40进入、Top80退出的缓冲组合研究。"""

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
from examples.fundamental_announcement_drift_study import (
    load_announcement_candidates,
)
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.fundamental_announcement_drift import (
    score_fundamental_announcement_drift_frame,
)
from monitoring.repository import MonitoringRepository
from portfolio.topn import (
    build_buffered_topn_selections,
    build_topn_selections,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "fundamental_announcement_drift_buffered_v2"
BASELINE_ID = "fundamental_announcement_drift_unbuffered_v1"
REPORT_PATH = Path("docs/research/fundamental-announcement-drift-buffered-study.md")
TOP_N = 40
EXIT_RANK = 80
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Fundamental Announcement Drift Buffered V2",
    category="portfolio_strategy",
    hypothesis="不改变公告漂移Alpha时，Top40进入Top80退出能否显著降低换手并保留样本外收益",
    definition={
        "alpha": {
            "source_strategy": "fundamental_announcement_drift_v1",
            "unchanged": True,
            "announcement_age_days": [0, 90],
            "factors": ["netprofit_yoy", "tr_yoy", "ocf_to_or"],
        },
        "portfolio": {
            "entry_rank": TOP_N,
            "exit_rank": EXIT_RANK,
            "weight": "equal",
            "rebalance": "monthly",
            "stale_or_ineligible_exit": True,
        },
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "comparison": "same_signal_unbuffered_top40",
            "main_candidate_fixed_before_test": True,
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
    """先登记V2组合语义，再读取季度财务大表。"""
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
    """V1与V2共享同一横截面分数，只改变组合持仓惯性。"""
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
        materialize_quality_financial_asof(connection, annual_only=False)
        candidates = load_announcement_candidates(connection)
        scores = _score_candidates(candidates)
        selections, holdings = _build_selections(scores)
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
        strategy_id: _run_candidate(strategy_id, targets, bars, calendar, benchmark)
        for strategy_id, targets in selections.items()
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
    correlations = _correlations(paths, runs)
    gate = evaluate_gate(
        metrics[STRATEGY_ID],
        metrics[BASELINE_ID],
        annual[STRATEGY_ID],
        correlations["quality_balanced_value"],
    )
    latest_holdings = holdings[
        holdings["strategy_id"].eq(STRATEGY_ID)
        & holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(metrics, annual, gate, correlations, latest_date),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "correlations": correlations,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "f_ann_date",
                "end_date",
            ]
        ].to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }


def _score_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """只计算一次冻结Alpha分数，避免V1与V2出现输入差异。"""
    frames = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_fundamental_announcement_drift_frame(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    return pd.concat(frames, ignore_index=True)


def _build_selections(
    scores: pd.DataFrame,
) -> tuple[dict[str, dict[str, dict[str, float]]], pd.DataFrame]:
    """将同一分数分别交给普通Top40和缓冲组合构建器。"""
    plain, plain_holdings = build_topn_selections(scores, "factor_score", TOP_N)
    buffered, buffered_holdings = build_buffered_topn_selections(
        scores,
        "factor_score",
        TOP_N,
        EXIT_RANK,
    )
    plain_holdings["strategy_id"] = BASELINE_ID
    buffered_holdings["strategy_id"] = STRATEGY_ID
    return (
        {
            BASELINE_ID: _equal_weight_targets(plain),
            STRATEGY_ID: _equal_weight_targets(buffered),
        },
        pd.concat([plain_holdings, buffered_holdings], ignore_index=True),
    )


def _equal_weight_targets(
    selections: dict[str, list[str]],
) -> dict[str, dict[str, float]]:
    return {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in selections.items()
        if symbols
    }


def _run_candidate(
    strategy_id: str,
    targets: dict[str, dict[str, float]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
    benchmark: pd.Series,
) -> RiskLayerRun:
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
                slice_result(
                    run.result,
                    f"{year}0101",
                    min(f"{year}1231", latest_date),
                ),
                benchmark,
            )
            for year in years
        }
        for strategy_id, run in runs.items()
    }


def _correlations(
    paths: RuntimePaths,
    runs: dict[str, RiskLayerRun],
) -> dict[str, float]:
    buffered_returns = runs[STRATEGY_ID].result.daily_values.pct_change()
    plain_returns = runs[BASELINE_ID].result.daily_values.pct_change()
    quality = MonitoringRepository(paths.monitoring_path).load_strategy_history(
        "quality_balanced_value_v1"
    )
    quality_returns = pd.Series(
        quality["daily_return"].astype(float).to_numpy(),
        index=pd.to_datetime(quality["trade_date"], format="%Y%m%d"),
    )
    return {
        "unbuffered": float(buffered_returns.corr(plain_returns)),
        "quality_balanced_value": float(buffered_returns.corr(quality_returns)),
    }


def evaluate_gate(
    buffered: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """V2既要可交易，也不能靠牺牲Alpha换取低换手。"""
    locked = buffered["locked_test"]
    full = buffered["full"]
    baseline_locked = baseline["locked_test"]
    baseline_full = baseline["full"]
    positive_years = sum(item["annualized_return"] > 0 for item in annual.values())
    checks = {
        "locked_test_annual_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_test_sharpe_at_least_055": locked["sharpe"] >= 0.55,
        "locked_test_drawdown_within_30pct": locked["max_drawdown"] >= -0.30,
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_drawdown_within_32pct": full["max_drawdown"] >= -0.32,
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "turnover_reduced_by_at_least_30pct": (
            full["annual_turnover"] <= baseline_full["annual_turnover"] * 0.70
        ),
        "full_return_within_1pct_of_v1": (
            full["annualized_return"] >= baseline_full["annualized_return"] - 0.01
        ),
        "locked_return_within_1pct_of_v1": (
            locked["annualized_return"]
            >= baseline_locked["annualized_return"] - 0.01
        ),
        "at_least_nine_positive_years": positive_years >= 9,
        "quality_correlation_at_most_075": abs(quality_correlation) <= 0.75,
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
            "固定公告漂移缓冲组合通过样本外和换手门槛，允许进入独立确认"
            if passed
            else "固定公告漂移缓冲组合未通过门槛，保留失败指纹且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新缓冲持仓"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    correlations: dict[str, float],
    latest_date: str,
) -> str:
    rows = []
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
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in annual[STRATEGY_ID].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Fundamental Announcement Drift Buffered V2 Study

- 数据截止：{latest_date}
- Alpha与V1完全一致，只把组合规则改为Top40进入、Top80退出。
- 过期公告或不再满足基本面门禁的股票立即退出，不受缓冲保护。
- 统一口径：季度f_ann_date as-of、Top40等权、月频、qfq、M0 T+1及原风险层。
- 与V1日收益相关性：{correlations['unbuffered']:.3f}。
- 与Quality Balanced Value日收益相关性：{correlations['quality_balanced_value']:.3f}。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## V2年度表现

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
