"""季度财报公告后基本面漂移策略的固定样本外研究。"""

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
    QUALITY_ASOF_TABLE,
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
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


STRATEGY_ID = "fundamental_announcement_drift_v1"
DIAGNOSTIC_ID = "quarterly_growth_drift_without_cash_v1"
REPORT_PATH = Path("docs/research/fundamental-announcement-drift-study.md")
TOP_N = 40
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Fundamental Announcement Drift V1",
    category="factor_strategy",
    hypothesis="季度财报公告后90日内的收入利润同步增长和现金验证，是否形成独立于Quality的漂移Alpha",
    definition={
        "factor": {
            "netprofit_yoy": {"weight": 1 / 3, "direction": 1},
            "tr_yoy": {"weight": 1 / 3, "direction": 1},
            "ocf_to_or": {"weight": 1 / 3, "direction": 1},
            "transform": "winsorize_5_95_then_zscore",
        },
        "gates": {
            "announcement_age_days": [0, 90],
            "roa_positive": True,
            "netprofit_yoy_positive": True,
            "tr_yoy_positive": True,
            "ocf_to_or_positive": True,
        },
        "diagnostics": {
            DIAGNOSTIC_ID: {
                "factors": ["netprofit_yoy", "tr_yoy"],
                "cash_gate": False,
                "uses_for_parameter_selection": False,
            },
        },
        "financial_visibility": "quality_financial_asof_quarterly_f_ann_date",
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
            "main_candidate_fixed_before_test": True,
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
    """先申请研究指纹，再物化季度财务as-of快照。"""
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
    """主策略和无现金验证对照共享统一季度财务快照。"""
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
        selections, holdings = _build_selections(candidates)
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
                "netprofit_yoy",
                "tr_yoy",
                "ocf_to_or",
            ]
        ].to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }


def load_announcement_candidates(connection: Any) -> pd.DataFrame:
    """只消费as-of门面输出，不直接读取原始财务表。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            q.end_date,
            q.f_ann_date,
            q.roa,
            q.ocf_to_or,
            q.netprofit_yoy,
            q.tr_yoy
        FROM features f
        JOIN {QUALITY_ASOF_TABLE} q
          ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
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


def _build_selections(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, dict[str, float]]], pd.DataFrame]:
    mappings: dict[str, dict[str, dict[str, float]]] = {}
    selected_frames: list[pd.DataFrame] = []
    variants = {DIAGNOSTIC_ID: False, STRATEGY_ID: True}
    for strategy_id, require_cash_quality in variants.items():
        frames = []
        for signal_date, group in candidates.groupby("signal_date", sort=True):
            scored = score_fundamental_announcement_drift_frame(
                group,
                require_cash_quality=require_cash_quality,
            )
            scored["signal_date"] = str(signal_date)
            frames.append(scored)
        scores = pd.concat(frames, ignore_index=True)
        mapping, selected = build_topn_selections(scores, "factor_score", TOP_N)
        mappings[strategy_id] = {
            date: {symbol: 1.0 / len(symbols) for symbol in symbols}
            for date, symbols in mapping.items()
            if symbols
        }
        selected["strategy_id"] = strategy_id
        selected_frames.append(selected)
    return mappings, pd.concat(selected_frames, ignore_index=True)


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
    main_returns = runs[STRATEGY_ID].result.daily_values.pct_change()
    diagnostic_returns = runs[DIAGNOSTIC_ID].result.daily_values.pct_change()
    quality = MonitoringRepository(paths.monitoring_path).load_strategy_history(
        "quality_balanced_value_v1"
    )
    quality_returns = pd.Series(
        quality["daily_return"].astype(float).to_numpy(),
        index=pd.to_datetime(quality["trade_date"], format="%Y%m%d"),
    )
    return {
        "growth_without_cash": float(main_returns.corr(diagnostic_returns)),
        "quality_balanced_value": float(main_returns.corr(quality_returns)),
    }


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    quality_correlation: float,
) -> dict[str, Any]:
    """固定绝对表现、稳定性、成本和低相关门槛。"""
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
            "固定季度公告漂移通过样本外及低相关门槛，允许进入独立确认"
            if passed
            else "固定季度公告漂移未通过门槛，保留失败指纹且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新Top40持仓"),
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
    return f"""# Fundamental Announcement Drift V1 Study

- 数据截止：{latest_date}
- 固定主策略：季度公告后90日内，利润与营收同比、ROA及经营现金流均为正。
- 三因子等权：利润同比、营收同比、OCF_TO_OR；Top40月频等权。
- 所有财务数据通过f_ann_date as-of门面，策略不读取原始财务表。
- 与Quality Balanced Value日收益相关性：{correlations['quality_balanced_value']:.3f}。
- 与无现金验证增长对照相关性：{correlations['growth_without_cash']:.3f}。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 主策略年度表现

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
