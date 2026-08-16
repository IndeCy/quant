"""季度防御趋势策略的固定样本外研究。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.defensive_momentum import score_defensive_momentum_frame
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


STRATEGY_ID = "quarterly_defensive_trend_v1"
DIAGNOSTIC_ID = "quarterly_positive_momentum_lowvol_v1"
REPORT_PATH = Path("docs/research/quarterly-defensive-trend-study.md")
TOP_N = 40
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quarterly Defensive Trend V1",
    category="factor_strategy",
    hypothesis="季度持有正中期动量池内低波股票，并用市场长趋势控制暴露，能否降低回撤和换手",
    definition={
        "factor": {
            "positive_skip_month_momentum_gate": {
                "formula": "(1+ret120)/(1+ret20)-1 > 0",
            },
            "low_volatility_60d": {
                "formula": "-std(daily_return,60)",
                "weight": 1.0,
                "transform": "winsorize_1_99_then_zscore",
            },
        },
        "universe": {
            "name_filter": "daily_st_plus_name_history_asof",
            "rules": "all_a_listed_3y_ex_st_delisted_suspended_bottom20_amount",
        },
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "security_rebalance": "quarterly",
        },
        "risk_overlay": {
            "portfolio_volatility": {
                "window": 20,
                "threshold": 0.45,
                "reduced_exposure": 0.30,
            },
            "market_trend": {
                "benchmark": "510300.SH",
                "rule": "ma120_gt_ma250",
                "normal_exposure": 1.0,
                "reduced_exposure": 0.30,
            },
            "combine": "minimum_exposure",
        },
        "diagnostics": {
            DIAGNOSTIC_ID: {
                "risk_overlay": "portfolio_volatility_only",
                "uses_for_parameter_selection": False,
            },
        },
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "main_candidate_fixed_before_test": True,
        },
        "methodology_version": "v1",
    },
)


@dataclass
class MarketTrendVolatilityController:
    """将市场长趋势与组合波动率合并为单一有效仓位上限。"""

    market_exposure: pd.Series
    vol_threshold: float = 0.45
    reduced_exposure: float = 0.30

    def update(
        self,
        date: pd.Timestamp,
        *,
        volatility: float,
        drawdown: float,
        daily_return: float,
    ) -> float:
        """使用截至当日的数据，返回下一交易日可用仓位。"""
        del drawdown, daily_return
        available = self.market_exposure.loc[:date].dropna()
        market_limit = float(available.iloc[-1]) if not available.empty else self.reduced_exposure
        volatility_limit = (
            self.reduced_exposure
            if volatility > self.vol_threshold
            else 1.0
        )
        return min(market_limit, volatility_limit)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在读取行情前登记完整策略语义指纹。"""
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
    """季度证券选择与两类风险层共享完全相同的行情和持仓。"""
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
        monthly_dates = load_month_end_signal_dates(connection)
        quarterly_dates = select_quarter_end_dates(monthly_dates)
        candidates = load_quarterly_candidates(connection, quarterly_dates)
        selections, holdings = build_quarterly_lowvol_selections(candidates)
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
    market_exposure = build_market_trend_exposure(benchmark)
    diagnostic = run_risk_layer_backtest(
        DIAGNOSTIC_ID,
        "GRID",
        selections,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )
    main = run_risk_layer_backtest(
        STRATEGY_ID,
        "NONE",
        selections,
        bars,
        calendar,
        benchmark,
        ExecutionModel(slippage_bps=5.0),
        exposure_controller=MarketTrendVolatilityController(market_exposure),
    )
    runs = {DIAGNOSTIC_ID: diagnostic, STRATEGY_ID: main}
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
    gate = evaluate_gate(metrics[STRATEGY_ID], annual[STRATEGY_ID])
    main_returns = main.result.daily_values.pct_change()
    diagnostic_returns = diagnostic.result.daily_values.pct_change()
    correlation = float(main_returns.corr(diagnostic_returns))
    latest_holdings = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_report(metrics, annual, gate, correlation, latest_date),
        encoding="utf-8",
    )
    return {
        "strategy_id": STRATEGY_ID,
        "latest_date": latest_date,
        "gate": gate,
        "period_metrics": metrics,
        "annual_metrics": annual,
        "diagnostic_correlation": correlation,
        "risk_trigger_days": int(main.exposure.lt(1.0).sum()),
        "average_exposure": float(main.exposure.mean()),
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "momentum_skip_20d",
                "vol60",
            ]
        ].to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }


def select_quarter_end_dates(monthly_dates: list[str]) -> list[str]:
    """每个自然季度只保留最后一个已完成的月末信号日。"""
    if not monthly_dates:
        return []
    frame = pd.DataFrame(
        {"signal_date": sorted(str(value) for value in monthly_dates)}
    )
    parsed = pd.to_datetime(frame["signal_date"], format="%Y%m%d")
    frame["quarter"] = parsed.dt.to_period("Q")
    return frame.groupby("quarter", sort=True)["signal_date"].max().tolist()


def build_market_trend_exposure(benchmark: pd.Series) -> pd.Series:
    """沪深300长趋势向上为满仓，否则仓位上限30%。"""
    normalized = benchmark.dropna().sort_index().astype(float)
    ma120 = normalized.rolling(120, min_periods=120).mean()
    ma250 = normalized.rolling(250, min_periods=250).mean()
    exposure = pd.Series(0.30, index=normalized.index, dtype=float)
    exposure.loc[ma120.gt(ma250)] = 1.0
    return exposure


def load_quarterly_candidates(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """读取季度末点时股票池，历史名称用于过滤ST与退市标签。"""
    if not signal_dates:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in signal_dates)
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
            WHERE f.trade_date IN ({placeholders})
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret20,
            f.ret120,
            f.vol60
        FROM features f
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN ({placeholders})
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
          AND f.ret20 IS NOT NULL
          AND f.ret120 IS NOT NULL
          AND f.vol60 IS NOT NULL
        ORDER BY f.trade_date, f.symbol
        """,
        [*signal_dates, *signal_dates],
    ).fetchdf()


def build_quarterly_lowvol_selections(
    candidates: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """按季度选择正中期动量池内波动率最低的40只股票。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_defensive_momentum_frame(group, momentum_weight=0.0)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    scored = pd.concat(frames, ignore_index=True)
    mapping, selected = build_topn_selections(scored, "factor_score", TOP_N)
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mapping.items()
        if symbols
    }
    return targets, selected


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


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """固定收益、风险、稳定性与换手门槛。"""
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
        "at_least_nine_positive_years": positive_years >= 9,
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
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
            "固定季度防御趋势通过样本外门槛，允许进入独立确认"
            if passed
            else "固定季度防御趋势未通过门槛，保留失败指纹且不注册生产策略"
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
    correlation: float,
    latest_date: str,
) -> str:
    rows: list[str] = []
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
    return f"""# Quarterly Defensive Trend V1 Study

- 数据截止：{latest_date}
- 固定主策略：正中期动量池内选择60日低波Top40，季度等权换股。
- 风险层：组合20日波动率超过45%或510300 MA120不高于MA250时，仓位上限30%。
- 归因对照：相同季度持仓只使用组合波动率风险层，不参与参数选择。
- 统一口径：全A上市满3年、剔除ST/退市/停牌/成交额最低20%，qfq、M0 T+1和5bps。
- 与无市场趋势控制版本日收益相关性：{correlation:.3f}。

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
