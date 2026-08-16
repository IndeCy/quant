"""Quality核心与季度低波卫星的固定70/30组合研究。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
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
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.quarterly_defensive_trend_study import (
    build_quarterly_lowvol_selections,
    load_quarterly_candidates,
    select_quarter_end_dates,
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
from strategies.quality_balanced_value_signal import (
    EXPECTED_WEIGHTS,
    build_quality_balanced_value_topn,
)
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)
STRATEGY_ID = "quality_quarterly_lowvol_blend_v1"
CORE_ID = "quality_balanced_value_core_v1"
SATELLITE_ID = "quarterly_positive_momentum_lowvol_satellite_v1"
REPORT_PATH = Path("docs/research/quality-quarterly-lowvol-blend-study.md")
CORE_ALLOCATION = 0.70
SATELLITE_ALLOCATION = 0.30
TRAIN_RANGE = ("20150101", "20181231")
VALIDATION_RANGE = ("20190101", "20211231")
LOCKED_TEST_START = "20220101"
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="Quality Quarterly LowVol Blend V1",
    category="portfolio_strategy",
    hypothesis="Quality价值核心与季度正动量低波卫星能否通过低相关性改善组合回撤而不显著损失收益",
    definition={
        "core": {
            "strategy": "quality_balanced_value_v1",
            "allocation": CORE_ALLOCATION,
            "factors": EXPECTED_WEIGHTS,
            "top_n": 20,
            "rebalance": "monthly",
        },
        "satellite": {
            "strategy": "positive_skip_month_momentum_gate_then_lowvol60",
            "allocation": SATELLITE_ALLOCATION,
            "top_n": 40,
            "rebalance": "quarterly",
        },
        "portfolio": {
            "combine": "sum_sleeve_weights",
            "overlap": "weights_add",
            "warmup": "core_100pct_until_first_satellite_selection",
        },
        "risk_overlay": {"scheme": "GRID", "window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "evaluation": {
            "train": TRAIN_RANGE,
            "validation": VALIDATION_RANGE,
            "locked_test_start": LOCKED_TEST_START,
            "main_candidate_fixed_before_test": True,
            "relative_to_core": True,
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
    """完整组合定义先取得指纹许可，再加载两条腿的数据。"""
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
    """在统一行情快照上生成核心、卫星和70/30组合目标。"""
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
        core_targets, core_holdings = _build_core(connection, monthly_dates, paths)
        quarterly_dates = select_quarter_end_dates(monthly_dates)
        satellite_candidates = load_quarterly_candidates(connection, quarterly_dates)
        satellite_targets, satellite_holdings = build_quarterly_lowvol_selections(
            satellite_candidates
        )
        blend_targets = blend_sleeve_targets(core_targets, satellite_targets)
        symbols = sorted(
            {
                symbol
                for targets in (core_targets, satellite_targets)
                for weights in targets.values()
                for symbol in weights
            }
        )
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
    runs = {
        CORE_ID: _run_candidate(CORE_ID, core_targets, bars, calendar, benchmark),
        SATELLITE_ID: _run_candidate(
            SATELLITE_ID,
            satellite_targets,
            bars,
            calendar,
            benchmark,
        ),
        STRATEGY_ID: _run_candidate(
            STRATEGY_ID,
            blend_targets,
            bars,
            calendar,
            benchmark,
        ),
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
    gate = evaluate_gate(metrics[STRATEGY_ID], metrics[CORE_ID], annual[STRATEGY_ID])
    correlations = _return_correlations(runs)
    latest_holdings = build_latest_blend_holdings(
        blend_targets,
        core_targets,
        satellite_targets,
        core_holdings,
        satellite_holdings,
    )
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
        "latest_holdings": latest_holdings.to_dict("records"),
        "report_path": str(output),
        "reused": False,
    }
def _build_core(
    connection: Any,
    signal_dates: list[str],
    paths: RuntimePaths,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """通过标准财务as-of门面重建冻结的Quality Balanced Value核心。"""
    create_quality_signal_date_table(connection, signal_dates)
    attach_quality_financial_databases(connection, _financial_paths(paths))
    materialize_quality_financial_asof(connection, annual_only=True)
    raw = load_annual_quality_candidates(connection)
    filtered = apply_quality_universe_filters(raw)
    with_adjustment = attach_report_adjustment_factors(connection, filtered)
    candidates, _ = build_quality_value_lowvol_candidates(with_adjustment)
    mapping, holdings = build_quality_balanced_value_topn(
        candidates,
        EXPECTED_WEIGHTS,
        top_n=20,
    )
    targets = {
        date: {symbol: 1.0 / len(symbols) for symbol in symbols}
        for date, symbols in mapping.items()
        if symbols
    }
    return targets, holdings
def blend_sleeve_targets(
    core_targets: dict[str, dict[str, float]],
    satellite_targets: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """月度更新核心，季度更新卫星；重叠股票直接累加袖套权重。"""
    output: dict[str, dict[str, float]] = {}
    current_satellite: dict[str, float] | None = None
    satellite_dates = sorted(satellite_targets)
    for date in sorted(core_targets):
        eligible = [value for value in satellite_dates if value <= date]
        if eligible:
            current_satellite = satellite_targets[eligible[-1]]
        core = core_targets[date]
        if current_satellite is None:
            output[date] = dict(core)
            continue
        combined: dict[str, float] = {}
        for symbol, weight in core.items():
            combined[symbol] = combined.get(symbol, 0.0) + CORE_ALLOCATION * weight
        for symbol, weight in current_satellite.items():
            combined[symbol] = (
                combined.get(symbol, 0.0) + SATELLITE_ALLOCATION * weight
            )
        output[date] = combined
    return output


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


def _return_correlations(
    runs: dict[str, RiskLayerRun],
) -> dict[str, float]:
    returns = {
        key: run.result.daily_values.pct_change()
        for key, run in runs.items()
    }
    return {
        "core_satellite": float(returns[CORE_ID].corr(returns[SATELLITE_ID])),
        "blend_core": float(returns[STRATEGY_ID].corr(returns[CORE_ID])),
        "blend_satellite": float(
            returns[STRATEGY_ID].corr(returns[SATELLITE_ID])
        ),
    }


def evaluate_gate(
    blend: dict[str, dict[str, float]],
    core: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """绝对门槛与相对核心改善必须同时满足。"""
    full = blend["full"]
    locked = blend["locked_test"]
    core_full = core["full"]
    core_locked = core["locked_test"]
    positive_years = sum(item["annualized_return"] > 0 for item in annual.values())
    checks = {
        "full_annual_return_at_least_10pct": full["annualized_return"] >= 0.10,
        "full_sharpe_at_least_065": full["sharpe"] >= 0.65,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "locked_test_positive_excess": locked["excess_return"] > 0,
        "annual_turnover_below_8x": full["annual_turnover"] <= 8.0,
        "at_least_nine_positive_years": positive_years >= 9,
        "full_drawdown_improves_core_by_3pct": (
            full["max_drawdown"] >= core_full["max_drawdown"] + 0.03
        ),
        "full_return_within_1_5pct_of_core": (
            full["annualized_return"] >= core_full["annualized_return"] - 0.015
        ),
        "full_sharpe_not_below_core": full["sharpe"] >= core_full["sharpe"],
        "locked_drawdown_not_worse_than_core_2pct": (
            locked["max_drawdown"] >= core_locked["max_drawdown"] - 0.02
        ),
    }
    return {"passed": all(checks.values()), "checks": checks, "positive_years": positive_years}


def build_latest_blend_holdings(
    blend_targets: dict[str, dict[str, float]],
    core_targets: dict[str, dict[str, float]],
    satellite_targets: dict[str, dict[str, float]],
    core_holdings: pd.DataFrame,
    satellite_holdings: pd.DataFrame,
) -> pd.DataFrame:
    """输出最新组合的袖套来源，便于研究页面解释重叠持仓。"""
    signal_date = max(blend_targets)
    satellite_date = max(date for date in satellite_targets if date <= signal_date)
    names = pd.concat(
        [
            core_holdings[["symbol", "name"]],
            satellite_holdings[["symbol", "name"]],
        ],
        ignore_index=True,
    ).drop_duplicates("symbol")
    rows = []
    for symbol, weight in blend_targets[signal_date].items():
        rows.append(
            {
                "signal_date": signal_date,
                "symbol": symbol,
                "target_weight": weight,
                "core_weight": CORE_ALLOCATION
                * core_targets[signal_date].get(symbol, 0.0),
                "satellite_weight": SATELLITE_ALLOCATION
                * satellite_targets[satellite_date].get(symbol, 0.0),
            }
        )
    return pd.DataFrame(rows).merge(names, on="symbol", how="left").sort_values(
        ["target_weight", "symbol"],
        ascending=[False, True],
    )


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
            "固定70/30组合通过绝对与相对核心门槛，允许进入独立确认"
            if passed
            else "固定70/30组合未通过门槛，保留失败指纹且不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新组合持仓"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    correlations: dict[str, float],
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
    return f"""# Quality Quarterly LowVol Blend V1 Study

- 数据截止：{latest_date}
- 固定组合：Quality Balanced Value核心70% + 季度正动量低波卫星30%。
- 两条腿保持各自原始因子和选股频率，组合层只合并目标权重。
- 统一口径：qfq、M0 T+1、5bps及20日组合波动率风险层。
- 核心与卫星日收益相关性：{correlations['core_satellite']:.3f}。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 组合年度表现

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
