"""业绩快报利润增长加速度的固定样本外研究。"""

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
from data.earnings_express import (
    EARNINGS_ACCELERATION_ASOF_TABLE,
    EarningsExpressPaths,
    attach_earnings_express_database,
    create_earnings_express_signal_date_table,
    materialize_earnings_acceleration_asof,
)
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.earnings_acceleration import score_earnings_acceleration_frame
from monitoring.repository import MonitoringRepository
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


STRATEGY_ID = "earnings_express_acceleration_v1"
REPORT_PATH = Path("docs/research/earnings-express-acceleration-v1.md")
TOP_N = 40
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="业绩快报利润增长加速度 V1",
    category="factor_strategy",
    hypothesis="正式财报前披露的年度业绩快报利润增长加速度，是否形成稳定独立Alpha",
    definition={
        "source_semantic_audit": {
            "source_column": "yoy_net_profit",
            "actual_meaning": "prior_year_net_income_amount",
            "formal_income_median_ratio": 1.0,
            "within_5pct_ratio": 0.969,
        },
        "factor": {
            "profit_growth": "current_net_income/prior_year_net_income-1",
            "profit_acceleration": "current_growth-prior_annual_express_growth",
            "gates": ["current_net_positive", "growth_positive", "acceleration_positive"],
            "transform": "cross_sectional_percentile_rank",
        },
        "visibility": {
            "annual_express_only": True,
            "publish_date_lte_signal_date": True,
            "latest_fiscal_year_age": [1, 2],
            "median_lead_days_vs_formal_report": 43,
        },
        "universe": {
            "name_filter": "daily_st_plus_name_history_asof",
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
    """先登记研究指纹，再读取业绩快报和行情大表。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=_express_data_version(paths),
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
    """构造公告日点时快报截面并运行统一 M0 回测。"""
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
        create_earnings_express_signal_date_table(connection, signal_dates)
        attach_earnings_express_database(
            connection,
            EarningsExpressPaths(paths.earnings_express_path),
        )
        materialize_earnings_acceleration_asof(connection)
        candidates = load_acceleration_candidates(connection)
        targets, holdings, candidate_counts = build_acceleration_targets(candidates)
        symbols = sorted(holdings["symbol"].astype(str).unique().tolist())
        if not symbols:
            raise ValueError("业绩快报利润增长加速度没有产生任何历史持仓")
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
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(
            metrics,
            annual,
            gate,
            quality_correlation,
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
        "candidate_counts": candidate_counts,
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "fiscal_year",
                "fiscal_year_age",
                "publish_date",
                "profit_growth",
                "prior_profit_growth",
                "profit_acceleration",
            ]
        ].to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }


def load_acceleration_candidates(connection: Any) -> pd.DataFrame:
    """连接统一行情与业绩快报 as-of 截面。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM express_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            e.fiscal_year,
            e.fiscal_year_age,
            e.publish_date,
            e.prior_publish_date,
            e.current_net_income,
            e.prior_year_net_income,
            e.profit_growth,
            e.prior_profit_growth,
            e.profit_acceleration
        FROM features f
        JOIN {EARNINGS_ACCELERATION_ASOF_TABLE} e
          ON f.trade_date = e.signal_date AND f.symbol = e.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM express_signal_dates)
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


def build_acceleration_targets(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, dict[str, float]]:
    """计算月度加速度排名并生成 Top40 等权目标。"""
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_earnings_acceleration_frame(group)
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


def build_annual_metrics(
    run: RiskLayerRun,
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, float]]:
    """输出2015年至数据截止日的年度指标。"""
    return {
        str(year): metric_summary(
            slice_result(
                run.result,
                f"{year}0101",
                min(f"{year}1231", latest_date),
            ),
            benchmark,
        )
        for year in range(2015, int(latest_date[:4]) + 1)
    }


def load_quality_correlation(paths: RuntimePaths, run: RiskLayerRun) -> float:
    """计算与生产 Quality 策略的日收益相关性。"""
    quality = MonitoringRepository(paths.monitoring_path).load_strategy_history(
        "quality_balanced_value_v1"
    )
    if quality.empty:
        return float("nan")
    quality_returns = pd.Series(
        quality["daily_return"].astype(float).to_numpy(),
        index=pd.to_datetime(quality["trade_date"], format="%Y%m%d"),
    )
    return float(run.result.daily_values.pct_change().corr(quality_returns))


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """应用研究前冻结的样本外、风险、成本和独立性门槛。"""
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
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "at_least_nine_positive_years": positive_years >= 9,
        "quality_correlation_at_most_075": (
            pd.notna(quality_correlation) and abs(quality_correlation) <= 0.75
        ),
    }
    return {"passed": all(checks.values()), "checks": checks, "positive_years": positive_years}


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存研究报告和最新持仓，不通过时禁止注册生产。"""
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
            "业绩快报加速度通过固定样本外门槛，允许进入独立确认"
            if passed
            else "业绩快报加速度未通过门槛，保留失败指纹且不注册生产策略"
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
    candidate_counts: dict[str, float],
    latest_date: str,
) -> str:
    """生成字段审计与回测结果一体化报告。"""
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
    return f"""# 业绩快报利润增长加速度 V1

- 数据截止：{latest_date}。
- 字段审计：源列 `yoy_net_profit` 实为上年净利润金额，门面已显式纠正。
- 交叉验证：与上一年度正式财报净利润中位数比值1.000，96.9%误差在5%内。
- 信息时效：业绩快报相对正式财报中位提前43天。
- 固定因子：正利润、正增长、增长继续加速；按加速度百分位排名。
- 执行：Top40月频等权，qfq、M0 T+1、5bps滑点及固定风险层。
- 与 Quality Balanced Value 日收益相关性：{quality_correlation:.3f}。
- 月度有效候选数：最少 {candidate_counts['min']:.0f}，中位数
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


def _express_data_version(paths: RuntimePaths) -> str:
    """绑定本地业绩快报数据文件版本。"""
    stat = paths.earnings_express_path.stat()
    return f"express:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
