"""大宗交易金额加权溢价因子的固定样本外研究。"""

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
from data.block_trades import (
    BLOCK_TRADE_ASOF_TABLE,
    attach_block_trade_database,
    create_block_trade_signal_date_table,
    materialize_block_trade_premium_asof,
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
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import run_risk_layer_backtest
from factors.block_trade_premium import score_block_trade_premium_frame
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


STRATEGY_ID = "block_trade_premium_v1"
REPORT_PATH = Path("docs/research/block-trade-premium-v1.md")
STUDY_START = "20150101"
TOP_N = 40
LOOKBACK_DAYS = 60
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="大宗交易溢价 V1",
    category="factor_strategy",
    hypothesis="大宗交易买方愿意支付的持续溢价是否形成稳定独立Alpha",
    definition={
        "factor": {
            "formula": "sum((block_price/raw_close-1)*amount)/sum(amount)",
            "lookback_calendar_days": LOOKBACK_DAYS,
            "positive_premium_only": True,
            "direction": "higher_is_better",
            "transform": "winsorize_1_99_then_cross_sectional_percentile_rank",
        },
        "visibility": {
            "trade_date_lte_signal_date": True,
            "same_day_event_available_after_close": True,
            "execution_next_trading_day": True,
        },
        "source": {
            "provider": "tushare",
            "endpoint": "block_trade",
            "cache": "block_trade_increment.duckdb",
            "price_reference": "same_day_raw_close",
        },
        "universe": {
            "security_filter": "inner_join_standard_stock_basic",
            "name_filter": "daily_st_plus_name_history_asof",
            "rules": "all_a_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        },
        "portfolio": {
            "top_n_max": TOP_N,
            "when_fewer": "hold_all_positive_candidates",
            "when_zero": "cash",
            "weight": "equal",
            "rebalance": "monthly",
        },
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "parameters_fixed_before_test": True,
            "momentum_overlap_is_attribution_only": True,
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
    """申请固定指纹后才读取大表和运行回测。"""
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
    """构造点时溢价截面并运行统一 M0 回测。"""
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
        create_block_trade_signal_date_table(connection, signal_dates)
        attach_block_trade_database(connection, paths.block_trade_path)
        materialize_block_trade_premium_asof(
            connection,
            lookback_days=LOOKBACK_DAYS,
        )
        candidates = load_block_trade_candidates(connection)
        targets, holdings, candidate_counts = build_block_trade_targets(
            candidates,
            signal_dates,
        )
        diagnostics = build_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("大宗交易溢价因子没有产生历史持仓")
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
                "latest_trade_date",
                "amount_weighted_premium",
                "premium_amount_share",
                "total_block_amount",
                "event_count",
                "ret120",
            ]
        ].to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }


def load_block_trade_candidates(connection: Any) -> pd.DataFrame:
    """将大宗交易截面与标准A股可交易股票池内连接。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM block_trade_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            b.latest_trade_date,
            b.total_block_amount,
            b.event_count,
            b.amount_weighted_premium,
            b.premium_amount_share,
            f.vol60,
            f.ret20,
            f.ret120
        FROM features f
        JOIN {BLOCK_TRADE_ASOF_TABLE} b
          ON f.trade_date = b.signal_date AND f.symbol = b.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.st_name IS NULL
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


def build_block_trade_targets(
    candidates: pd.DataFrame,
    signal_dates: list[str],
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """每月选择最多40只正溢价股票，不用零分股票补足名额。"""
    targets: dict[str, dict[str, float]] = {}
    holdings: list[pd.DataFrame] = []
    counts: list[int] = []
    for signal_date in signal_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        scored = score_block_trade_premium_frame(group)
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
        "months_below_top_n": float((values < TOP_N).sum()),
        "empty_months": float((values == 0).sum()),
    }


def build_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """归因溢价信号与动量的关系及成交强度。"""
    correlations: list[float] = []
    overlaps: list[float] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        valid = group.dropna(subset=["amount_weighted_premium", "ret120"])
        positive = valid[valid["amount_weighted_premium"].gt(0)]
        if len(positive) >= 2:
            corr = positive["amount_weighted_premium"].rank().corr(
                positive["ret120"].rank()
            )
            if pd.notna(corr):
                correlations.append(float(corr))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        momentum = set(valid.nlargest(min(TOP_N, len(valid)), "ret120")["symbol"].astype(str))
        overlaps.append(len(selected & momentum) / max(1, len(selected)))
    selected_premium = pd.to_numeric(
        holdings["amount_weighted_premium"],
        errors="coerce",
    )
    return {
        "median_spearman_with_ret120": (
            float(pd.Series(correlations).median()) if correlations else float("nan")
        ),
        "median_holding_overlap_with_momentum": (
            float(pd.Series(overlaps).median()) if overlaps else float("nan")
        ),
        "latest_holding_overlap_with_momentum": (
            overlaps[-1] if overlaps else float("nan")
        ),
        "median_selected_premium": float(selected_premium.median()),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存报告和持仓，不通过时禁止注册生产。"""
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
            "大宗交易溢价通过固定样本外门槛，允许进入独立确认"
            if passed
            else "大宗交易溢价未通过固定门槛，保留失败指纹且不注册生产策略"
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
    """生成大宗交易溢价研究报告。"""
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
    return f"""# 大宗交易金额加权溢价 V1

- 数据截止：{latest_date}；过去{LOOKBACK_DAYS}天交易按金额加权。
- 溢价使用大宗成交价相对同日未复权收盘价，信号收盘后生成、T+1成交。
- 不按席位名称做机构标签，只保留金额加权溢价为正的股票。
- 执行：月频最多Top40等权，qfq、M0、5bps及固定风险层。
- 与 Quality Balanced Value 日收益相关性：{quality_correlation:.3f}。
- 与120日动量Spearman中位数：
  {diagnostics['median_spearman_with_ret120']:.3f}；持仓重叠中位数
  {diagnostics['median_holding_overlap_with_momentum']:.1%}。
- 历史入选溢价中位数：{diagnostics['median_selected_premium']:.2%}。
- 正溢价候选数：最少 {candidate_counts['min']:.0f}，中位数
  {candidate_counts['median']:.0f}，最新 {candidate_counts['latest']:.0f}；
  少于Top40共 {candidate_counts['months_below_top_n']:.0f} 个月。

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
    """绑定大宗交易缓存和统一行情版本。"""
    parts = []
    for label, path in [
        ("block_trade", paths.block_trade_path),
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
