"""公募基金持仓广度变化的固定样本外研究。"""

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
from data.fund_ownership import (
    FUND_OWNERSHIP_ASOF_TABLE,
    attach_fund_ownership_database,
    create_fund_ownership_signal_date_table,
    materialize_fund_ownership_breadth_asof,
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
from factors.fund_ownership_breadth import score_fund_ownership_breadth_frame
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


STRATEGY_ID = "fund_ownership_breadth_v1"
REPORT_PATH = Path("docs/research/fund-ownership-breadth-v1.md")
TOP_N = 40
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="公募基金持仓广度变化 V1",
    category="factor_strategy",
    hypothesis="公募基金产品持有占比的季度扩张，能否形成低频且独立的机构行为 Alpha",
    definition={
        "factor": {
            "formula": (
                "current_distinct_product_holders/current_products"
                "-prior_distinct_product_holders/prior_products"
            ),
            "direction": "higher_is_better",
            "positive_change_only": True,
            "transform": "cross_sectional_percentile_rank",
        },
        "source": {
            "provider": "tushare",
            "endpoints": ["fund_basic", "fund_portfolio"],
            "cache": "fund_ownership_increment.duckdb",
        },
        "product_panel": {
            "fund_status": "L_plus_D",
            "product_identity": "management_plus_normalized_name",
            "representative_share": "per_period_earliest_found_date_then_code",
            "positions": "top10_A_share_by_mkv",
        },
        "visibility": {
            "ann_date_lte_signal_date": True,
            "q1_deadline": "0430",
            "q2_deadline": "0831",
            "q3_deadline": "1031",
            "annual_deadline": "next_year_0430",
        },
        "universe": {
            "name_filter": "daily_st_plus_name_history_asof",
            "rules": "all_a_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        },
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "first_month_end_after_new_period_available",
        },
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "quality_return_correlation_max": 0.75,
            "parameters_fixed_before_locked_test": True,
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
    """先申请确定性研究指纹，再从本地缓存运行研究。"""
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
    """构造产品持仓广度点时截面并执行统一 M0 回测。"""
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
        create_fund_ownership_signal_date_table(connection, signal_dates)
        attach_fund_ownership_database(connection, paths.fund_ownership_path)
        materialize_fund_ownership_breadth_asof(connection)
        candidates = load_candidates(connection)
        targets, holdings, candidate_counts = build_targets(candidates)
        diagnostics = build_momentum_diagnostics(candidates, holdings)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("基金持仓广度因子没有产生历史持仓")
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
        "candidate_counts": candidate_counts,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "current_period",
                "prior_period",
                "current_product_holders",
                "prior_product_holders",
                "breadth_change",
                "ret120",
            ]
        ].to_dict("records"),
        "report_path": str(report_path),
        "reused": False,
    }


def load_candidates(connection: Any) -> pd.DataFrame:
    """连接统一股票池与基金持仓广度 as-of 截面。"""
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
                SELECT signal_date FROM fund_ownership_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            o.current_period,
            o.prior_period,
            o.latest_ann_date,
            o.current_product_holders,
            o.prior_product_holders,
            o.current_total_products,
            o.prior_total_products,
            o.current_breadth_share,
            o.prior_breadth_share,
            o.breadth_change,
            f.vol60,
            f.ret20,
            f.ret120
        FROM features f
        JOIN {FUND_OWNERSHIP_ASOF_TABLE} o
          ON f.trade_date = o.signal_date AND f.symbol = o.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
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
          AND o.latest_ann_date <= f.trade_date
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """每个新报告期只在首次可用月末生成一次 Top40 目标。"""
    if candidates.empty:
        return {}, candidates, {"min": 0.0, "median": 0.0, "latest": 0.0}
    first_dates = (
        candidates.groupby("current_period")["signal_date"].min().to_dict()
    )
    event_frame = candidates[
        candidates.apply(
            lambda row: str(row["signal_date"])
            == str(first_dates[row["current_period"]]),
            axis=1,
        )
    ].copy()
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in event_frame.groupby("signal_date", sort=True):
        scored = score_fund_ownership_breadth_frame(group)
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
        signal_date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for signal_date, symbols in mapping.items()
    }
    count_series = pd.Series(counts, dtype=float)
    return targets, holdings, {
        "min": float(count_series.min()),
        "median": float(count_series.median()),
        "latest": float(count_series.iloc[-1]),
    }


def build_momentum_diagnostics(
    candidates: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, float]:
    """衡量机构广度变化是否只是价格动量的代理。"""
    correlations: list[float] = []
    overlaps: list[float] = []
    selected_dates = set(holdings["signal_date"].astype(str))
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        if str(signal_date) not in selected_dates:
            continue
        valid = group.dropna(subset=["breadth_change", "ret120"])
        if len(valid) < TOP_N:
            continue
        correlation = valid["breadth_change"].rank().corr(valid["ret120"].rank())
        if pd.notna(correlation):
            correlations.append(float(correlation))
        selected = set(
            holdings.loc[
                holdings["signal_date"].astype(str).eq(str(signal_date)),
                "symbol",
            ].astype(str)
        )
        momentum = set(valid.nlargest(TOP_N, "ret120")["symbol"].astype(str))
        overlaps.append(len(selected & momentum) / TOP_N)
    return {
        "median_spearman_with_ret120": (
            float(pd.Series(correlations).median()) if correlations else float("nan")
        ),
        "median_top40_overlap_with_momentum": (
            float(pd.Series(overlaps).median()) if overlaps else float("nan")
        ),
        "latest_top40_overlap_with_momentum": (
            overlaps[-1] if overlaps else float("nan")
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档报告与最新持仓，失败结果同样保留确定性指纹。"""
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
            "基金持仓广度通过固定样本外门槛，允许进入独立确认"
            if passed
            else "基金持仓广度未通过固定门槛，保留失败指纹且不注册生产策略"
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
    """生成机构持仓广度的可解释研究报告。"""
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
    return f"""# 公募基金持仓广度变化 V1

- 数据截止：{latest_date}。
- 固定因子：产品持有占比的季度变化，只保留正向扩张并做横截面排名。
- 产品口径：存续与已清盘开放式基金，归并份额类别，每产品前十大 A 股。
- 可见性：实际公告日不晚于信号日，报告期仅在保守披露截止日后使用。
- 执行：Top40低频等权，qfq、M0 T+1、5bps滑点及固定风险层。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与120日动量Spearman中位数：
  {diagnostics['median_spearman_with_ret120']:.3f}；Top40重叠中位数：
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
- 每期正向候选数：最少 {candidate_counts['min']:.0f}，中位数
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


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金持仓缓存和统一行情版本。"""
    parts = []
    for label, path in [
        ("fund_ownership", paths.fund_ownership_path),
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
