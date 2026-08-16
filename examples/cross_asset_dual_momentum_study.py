"""五资产 ETF 双动量配置的固定多折研究。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.fund_portfolio import FundPortfolioPanel, load_fund_portfolio_panel
from examples.quality_factor_study_support import (
    build_period_metrics,
    metric_summary,
    slice_result,
)
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.etf_momentum import calculate_trailing_momentum, month_end_signal_dates
from monitoring.repository import MonitoringRepository
from portfolio.defensive_rotation import build_defensive_rotation_targets
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "cross_asset_dual_momentum_v1"
REPORT_PATH = Path("docs/research/cross-asset-dual-momentum-v1.md")
STUDY_START = "20150101"
LOAD_START = "20130101"
RISKY_ASSETS = ["510300.SH", "510500.SH", "159915.SZ", "518880.SH"]
DEFENSIVE_ASSET = "511010.SH"
ASSET_NAMES = {
    "510300.SH": "沪深300",
    "510500.SH": "中证500",
    "159915.SZ": "创业板",
    "518880.SH": "黄金",
    "511010.SH": "5年国债",
}
FOLDS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="五资产ETF双动量配置 V1",
    category="allocation_strategy",
    hypothesis="跨股票、黄金和国债的绝对/相对动量能否提供独立于Quality的低回撤收益",
    definition={
        "asset_pool": {
            "risky": RISKY_ASSETS,
            "defensive": DEFENSIVE_ASSET,
            "selection_basis": "economic_role_fixed_before_backtest",
        },
        "factor": {
            "name": "trailing_total_return",
            "lookback_trading_days": 252,
            "absolute_filter": "positive",
            "relative_rank": "descending",
        },
        "portfolio": {
            "top_n": 2,
            "slot_weight": 0.5,
            "unfilled_slots": DEFENSIVE_ASSET,
            "rebalance": "monthly",
        },
        "risk_overlay": "none",
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "folds": FOLDS,
            "quality_correlation_max": 0.60,
            "parameters_fixed_before_test": True,
        },
        "gate": {
            "full_annual_return_min": 0.05,
            "full_max_drawdown_floor": -0.25,
            "full_sharpe_min": 0.60,
            "full_calmar_min": 0.25,
            "full_positive_excess": True,
            "positive_folds_min": 3,
            "worst_fold_drawdown_floor": -0.25,
            "median_fold_sharpe_min": 0.40,
            "annual_turnover_max": 4.0,
            "quality_correlation_max": 0.60,
        },
        "promotion_scope": "research_only",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记研究指纹，再读取基金历史大表并执行 M0 回测。"""
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
        result, run, holdings = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, run, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], RiskLayerRun, pd.DataFrame]:
    """构造点时动量、组合权重并统一评价四个阶段。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*RISKY_ASSETS, DEFENSIVE_ASSET],
        start_date=LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    scores = calculate_trailing_momentum(
        panel.adjusted_close,
        signals,
        RISKY_ASSETS,
        lookback_days=252,
    )
    targets, holdings = build_defensive_rotation_targets(
        scores,
        RISKY_ASSETS,
        DEFENSIVE_ASSET,
        top_n=2,
    )
    if not targets:
        raise ValueError("ETF 双动量没有产生任何月度目标组合")
    benchmark = _benchmark_curve(panel)
    run = run_risk_layer_backtest(
        STRATEGY_ID,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        _execution_model(),
    )
    periods = {
        key: (
            start,
            panel.latest_common_date if end == "LATEST" else end,
        )
        for key, (start, end) in FOLDS.items()
    }
    periods["full"] = (STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    quality_correlation = load_quality_correlation(paths, run)
    gate = evaluate_gate(metrics, quality_correlation)
    annual = build_annual_metrics(run, benchmark, panel.latest_common_date)
    exposure = build_asset_exposure(holdings)
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
            exposure,
            panel,
            latest_holdings,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "latest_date": panel.latest_common_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "quality_return_correlation": quality_correlation,
            "gate": gate,
            "asset_exposure": exposure,
            "data_coverage": panel.coverage,
            "latest_holdings": latest_holdings.to_dict("records"),
            "report_path": str(report_path),
            "reused": False,
        },
        run,
        holdings,
    )


def _benchmark_curve(panel: FundPortfolioPanel) -> pd.Series:
    """以同一数据面板中的 510300 qfq 收盘价作为基准。"""
    values = panel.adjusted_close["510300.SH"].astype(float)
    return values / float(values.iloc[0])


def _execution_model() -> ExecutionModel:
    """ETF 不收印花税，其他成交参数沿用 M0。"""
    return ExecutionModel(stamp_tax_rate=0.0, slippage_bps=5.0)


def load_quality_correlation(paths: RuntimePaths, run: RiskLayerRun) -> float:
    """衡量策略与当前 Quality Core 的日收益独立性。"""
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
    quality_correlation: float,
) -> dict[str, Any]:
    """应用研究前冻结的收益、回撤、换手和独立性门槛。"""
    full = metrics["full"]
    folds = [metrics[key] for key in FOLDS]
    checks = {
        "full_annual_return_at_least_5pct": full["annualized_return"] >= 0.05,
        "full_drawdown_within_25pct": full["max_drawdown"] >= -0.25,
        "full_sharpe_at_least_060": full["sharpe"] >= 0.60,
        "full_calmar_at_least_025": full["calmar"] >= 0.25,
        "full_positive_excess": full["excess_return"] > 0,
        "at_least_three_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 3
        ),
        "worst_fold_drawdown_within_25pct": (
            min(item["max_drawdown"] for item in folds) >= -0.25
        ),
        "median_fold_sharpe_at_least_040": (
            float(pd.Series([item["sharpe"] for item in folds]).median()) >= 0.40
        ),
        "annual_turnover_below_4x": full["annual_turnover"] <= 4.0,
        "quality_correlation_at_most_060": (
            pd.notna(quality_correlation) and abs(quality_correlation) <= 0.60
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def build_annual_metrics(
    run: RiskLayerRun,
    benchmark: pd.Series,
    latest_date: str,
) -> dict[str, dict[str, float]]:
    """按自然年输出策略与基准对比。"""
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


def build_asset_exposure(holdings: pd.DataFrame) -> dict[str, float]:
    """统计各资产在月度目标中的平均权重。"""
    if holdings.empty:
        return {}
    months = holdings["signal_date"].nunique()
    return {
        str(symbol): float(group["target_weight"].sum() / months)
        for symbol, group in holdings.groupby("symbol", sort=True)
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    holdings: pd.DataFrame,
) -> None:
    """保存报告、净值和完整月度目标，失败结果同样可回溯。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav.csv"
    pd.DataFrame(
        {
            "trade_date": run.result.daily_values.index,
            "strategy_nav": (
                run.result.daily_values / float(run.result.daily_values.iloc[0])
            ).values,
        }
    ).to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "monthly_targets.csv"
    holdings.to_csv(holdings_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "跨资产双动量通过研究门槛，仅允许进入独立前瞻确认"
            if passed
            else "跨资产双动量未通过固定门槛，不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "多折研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "策略每日净值"),
            ExperimentArtifact("monthly_targets", holdings_path, "月度目标组合"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    exposure: dict[str, float],
    panel: FundPortfolioPanel,
    latest_holdings: pd.DataFrame,
) -> str:
    """渲染跨资产策略研究报告。"""
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
    exposure_rows = "\n".join(
        f"| {symbol} | {ASSET_NAMES[symbol]} | {weight:.1%} |"
        for symbol, weight in exposure.items()
    )
    holding_rows = "\n".join(
        f"| {row.symbol} | {ASSET_NAMES[str(row.symbol)]} | "
        f"{float(row.target_weight):.1%} | {row.role} |"
        for row in latest_holdings.itertuples(index=False)
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# 五资产 ETF 双动量配置 V1

- 数据共同截止：{panel.latest_common_date}。
- 固定风险资产：沪深300、中证500、创业板、黄金；防守资产：5年国债。
- 每月按过去252个交易日收益选择正动量前两名，空余50%槽位进入国债。
- 使用qfq、M0 T+1、5bps滑点；ETF印花税为0，不叠加波动率风险层。
- 与Quality Balanced Value日收益相关性：{quality_correlation:.3f}。
- ETF历史库缺少可靠涨跌停字段，本研究只能按停牌、价格和成交量拦截。

| 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 平均资产暴露

| 代码 | 资产 | 平均目标权重 |
|---|---|---:|
{exposure_rows}

## 最新目标

| 代码 | 资产 | 权重 | 角色 |
|---|---|---:|---|
{holding_rows}

## 固定研究门槛

{checks}

结论：{'进入独立前瞻确认，不注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定基金基线和增量数据库版本。"""
    parts: list[str] = []
    for label, path in [
        ("fund_history", paths.fund_daily_history_path),
        ("fund_increment", paths.benchmark_increment_path),
        ("monitoring", paths.monitoring_path),
    ]:
        if not path.exists():
            parts.append(f"{label}:missing")
            continue
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
