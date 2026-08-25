"""前 252 日最高收盘突破强度的固定样本外研究。"""

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
from data.price_high import PRICE_BREAKOUT_TABLE, materialize_price_high_breakout
from examples.earnings_express_acceleration_study import (
    LOCKED_TEST_START,
    TRAIN_RANGE,
    VALIDATION_RANGE,
    build_annual_metrics,
    evaluate_gate,
    load_quality_correlation,
)
from examples.price_high_proximity_study import (
    TOP_N,
    WINDOW,
    _data_version,
    build_momentum_diagnostics,
    build_targets,
)
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.price_high_proximity import score_price_high_breakout_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "price_high_breakout_252d_v2"
REPORT_PATH = Path("docs/research/price-high-breakout-252d-v2.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="52周前高突破强度 V2",
    category="factor_strategy",
    hypothesis="消除当日新高并列后，前252日高点突破幅度能否形成稳定且可执行的Alpha",
    definition={
        "correction_from": "price_high_proximity_252d_v1",
        "correction_reason": "当日纳入滚动最高价导致大量精确1.0并列并按代码截断",
        "factor": {
            "formula": "qfq_close/max(qfq_close,prior_252_trading_days)",
            "direction": "higher_is_better",
            "window": WINDOW,
            "transform": "cross_sectional_percentile_rank",
        },
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "unchanged": [
            "Top40",
            "monthly_equal_weight",
            "universe",
            "M0_T_plus_1",
            "qfq",
            "5bps_slippage",
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
    """登记修正版独立指纹，相同数据版本禁止重算。"""
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
    """构造前高突破截面并执行唯一一次修正版 M0 回测。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_price_high_breakout(connection, window=WINDOW)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = load_month_end_signal_dates(connection)
        candidates = load_candidates(connection, signal_dates)
        targets, holdings, candidate_counts = build_targets(
            candidates,
            scorer=score_price_high_breakout_frame,
        )
        diagnostics = build_momentum_diagnostics(
            candidates,
            holdings,
            factor_column="breakout_strength",
        )
        tie_diagnostics = build_tie_diagnostics(candidates)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("52周前高突破强度没有产生历史持仓")
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
        "momentum_diagnostics": diagnostics,
        "tie_diagnostics": tie_diagnostics,
        "candidate_counts": candidate_counts,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "breakout_strength",
                "prior_max_close",
                "ret20",
                "ret120",
                "vol60",
            ]
        ].to_dict("records"),
        "report_path": str(report_path),
        "reused": False,
    }


def load_candidates(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """读取标准股票池与同日突破强度。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE price_breakout_signal_dates("
        "signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO price_breakout_signal_dates VALUES (?)",
        [(str(item),) for item in signal_dates],
    )
    return connection.execute(
        f"""
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                h.name AS asof_name,
                ROW_NUMBER() OVER(
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM features f
            JOIN name_history h ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (
                SELECT signal_date FROM price_breakout_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            p.prior_max_close,
            p.breakout_strength,
            f.ret20,
            f.ret120,
            f.vol60
        FROM features f
        JOIN {PRICE_BREAKOUT_TABLE} p
          ON f.trade_date = p.trade_date AND f.symbol = p.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (
                SELECT signal_date FROM price_breakout_signal_dates
              )
          AND f.st_name IS NULL
          AND NOT REGEXP_MATCHES(COALESCE(na.asof_name, sb.name, ''), 'ST|退')
          AND NOT f.is_suspended
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
          AND sb.list_date IS NOT NULL
          AND STRPTIME(f.trade_date, '%Y%m%d')
              >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
          AND (sb.delist_date IS NULL OR sb.delist_date > f.trade_date)
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_tie_diagnostics(candidates: pd.DataFrame) -> dict[str, float]:
    """确认修正后 Top40 截止位不再被大面积精确并列主导。"""
    tie_counts: list[int] = []
    for _, group in candidates.groupby("signal_date", sort=True):
        values = group["breakout_strength"].dropna().sort_values(ascending=False)
        if len(values) < TOP_N:
            continue
        cutoff = float(values.iloc[TOP_N - 1])
        tie_counts.append(int(values.eq(cutoff).sum()))
    return {
        "median_cutoff_tie_count": (
            float(pd.Series(tie_counts).median()) if tie_counts else float("nan")
        ),
        "maximum_cutoff_tie_count": (
            float(max(tie_counts)) if tie_counts else float("nan")
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档修正版报告，之后不再继续高点参数变体。"""
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
            "前高突破强度通过固定样本外门槛，允许进入独立确认"
            if passed
            else "前高突破强度修正后仍未通过固定门槛，终止52周高点方向"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "修正版研究报告"),
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
    """生成前高突破修正版研究报告。"""
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
    return f"""# 52周前高突破强度 V2

- 数据截止：{latest_date}。
- 唯一修正：最高收盘窗口排除当日，以突破幅度消除 V1 精确1.0并列。
- 固定因子：`qfq_close / 前252个交易日最高qfq_close`，越高越好。
- 执行：Top40月频等权，qfq、M0 T+1、5bps滑点及固定风险层。
- 截止位并列数中位数：
  {tie_diagnostics['median_cutoff_tie_count']:.0f}，最大
  {tie_diagnostics['maximum_cutoff_tie_count']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与120日动量Spearman中位数：
  {diagnostics['median_spearman_with_ret120']:.3f}；Top40重叠中位数：
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
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

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止52周高点方向'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
