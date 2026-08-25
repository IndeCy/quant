"""固定跨资产双动量叠加既有波动率风险层的归因研究。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import cross_asset_dual_momentum_study as base
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from factors.etf_momentum import calculate_trailing_momentum, month_end_signal_dates
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


STRATEGY_ID = "cross_asset_dual_momentum_risk_overlay_v1"
REPORT_PATH = Path("docs/research/cross-asset-dual-momentum-risk-overlay-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="五资产ETF双动量固定风险层 V1",
    category="risk_attribution",
    hypothesis="既有20日波动率风险层能否修复双动量在快速股灾中的退出滞后",
    definition={
        "base_strategy": {
            "strategy_id": base.STRATEGY_ID,
            "asset_pool": {
                "risky": base.RISKY_ASSETS,
                "defensive": base.DEFENSIVE_ASSET,
            },
            "factor": "252d_positive_relative_momentum",
            "portfolio": "monthly_top2_equal_slots_with_bond_fill",
        },
        "risk_overlay": {
            "scheme": "GRID",
            "source": "existing_quality_production_rule",
            "volatility_window": 20,
            "threshold": 0.45,
            "normal_exposure": 1.0,
            "reduced_exposure": 0.30,
            "evaluation_frequency": "daily_close_for_next_trading_day",
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "slippage_bps": 5.0,
            "stamp_tax_rate": 0.0,
        },
        "evaluation": {
            "folds": base.FOLDS,
            "same_gate_as_base": True,
            "drawdown_improvement_vs_base_min": 0.15,
            "promotion_scope": "retrospective_attribution_only",
        },
        "parameters_selected_from_this_backtest": False,
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记研究身份，再读取基金面板和执行回测。"""
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
    """保持 Alpha 不变，仅叠加现有风险层并比较原策略。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*base.RISKY_ASSETS, base.DEFENSIVE_ASSET],
        start_date=base.LOAD_START,
        end_date=as_of_date,
    )
    signals = [
        date
        for date in month_end_signal_dates(panel.calendar)
        if date >= pd.Timestamp(base.STUDY_START)
    ]
    scores = calculate_trailing_momentum(
        panel.adjusted_close,
        signals,
        base.RISKY_ASSETS,
        lookback_days=252,
    )
    targets, holdings = build_defensive_rotation_targets(
        scores,
        base.RISKY_ASSETS,
        base.DEFENSIVE_ASSET,
        top_n=2,
    )
    benchmark = base._benchmark_curve(panel)
    run = run_risk_layer_backtest(
        STRATEGY_ID,
        "GRID",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        base._execution_model(),
        vol_window=20,
        vol_threshold=0.45,
        reduced_exposure=0.30,
    )
    periods = {
        key: (
            start,
            panel.latest_common_date if end == "LATEST" else end,
        )
        for key, (start, end) in base.FOLDS.items()
    }
    periods["full"] = (base.STUDY_START, panel.latest_common_date)
    metrics = build_period_metrics({STRATEGY_ID: run.result}, benchmark, periods)[
        STRATEGY_ID
    ]
    quality_correlation = base.load_quality_correlation(paths, run)
    base_result = load_base_result(paths)
    gate = evaluate_gate(
        metrics,
        quality_correlation,
        base_result["period_metrics"],
    )
    annual = base.build_annual_metrics(run, benchmark, panel.latest_common_date)
    latest_holdings = holdings[
        holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    risk_summary = build_risk_summary(run)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            metrics,
            annual,
            gate,
            quality_correlation,
            risk_summary,
            base_result["period_metrics"],
            run.events,
            panel.latest_common_date,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "base_strategy_id": base.STRATEGY_ID,
            "latest_date": panel.latest_common_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "quality_return_correlation": quality_correlation,
            "risk_summary": risk_summary,
            "gate": gate,
            "base_period_metrics": base_result["period_metrics"],
            "latest_holdings": latest_holdings.to_dict("records"),
            "promotion_allowed": False,
            "promotion_block_reason": (
                "风险层研究使用了完整历史回撤归因，必须另行前瞻确认"
            ),
            "report_path": str(report_path),
            "reused": False,
        },
        run,
        holdings,
    )


def load_base_result(paths: RuntimePaths) -> dict[str, Any]:
    """从结构化实验仓库读取未叠加风险层的固定基线。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        row = connection.execute(
            """
            SELECT metrics_json
            FROM experiment_runs
            WHERE experiment_id = ?
              AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [base.STRATEGY_ID],
        ).fetchone()
    if row is None:
        raise ValueError("缺少跨资产双动量 V1 结构化基线")
    result = json.loads(str(row[0] or "{}"))
    if "period_metrics" not in result:
        raise ValueError("跨资产双动量 V1 缺少区间指标")
    return result


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
    base_metrics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """沿用原门槛，并要求最大回撤至少改善15个百分点。"""
    original = base.evaluate_gate(metrics, quality_correlation)
    improvement = (
        metrics["full"]["max_drawdown"]
        - base_metrics["full"]["max_drawdown"]
    )
    checks = {
        **original["checks"],
        "full_drawdown_improves_base_by_15pct": improvement >= 0.15,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "full_drawdown_improvement": float(improvement),
    }


def build_risk_summary(run: RiskLayerRun) -> dict[str, float]:
    """统计风险层真实触发频率和平均仓位。"""
    exposure = run.exposure.dropna()
    reduced = exposure.lt(1.0)
    return {
        "average_exposure": float(exposure.mean()),
        "reduced_trading_days": float(reduced.sum()),
        "reduced_day_ratio": float(reduced.mean()),
        "trigger_events": float(
            (
                run.events["exposure"].lt(1.0).sum()
                if not run.events.empty
                else 0
            )
        ),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    holdings: pd.DataFrame,
) -> None:
    """归档风险事件、净值和月度目标。"""
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
            "target_exposure": run.exposure.reindex(
                run.result.daily_values.index
            ).ffill().values,
        }
    ).to_csv(nav_path, index=False)
    holdings_path = attempt.output_dir / "monthly_targets.csv"
    holdings.to_csv(holdings_path, index=False)
    events_path = attempt.output_dir / "risk_events.csv"
    run.events.to_csv(events_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "固定风险层显著降低回撤，允许进入独立前瞻确认"
            if passed
            else "固定风险层仍未通过稳健性门槛，不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "风险层归因报告"),
            ExperimentArtifact("daily_nav", nav_path, "风险层策略净值与仓位"),
            ExperimentArtifact("monthly_targets", holdings_path, "原始月度目标"),
            ExperimentArtifact("risk_events", events_path, "风险层触发事件"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    risk_summary: dict[str, float],
    base_metrics: dict[str, dict[str, float]],
    events: pd.DataFrame,
    latest_date: str,
) -> str:
    """生成风险层是否修复双动量回撤的对照报告。"""
    comparison_rows = "\n".join(
        f"| {period} | {base_metrics[period]['annualized_return']:.2%} | "
        f"{item['annualized_return']:.2%} | "
        f"{base_metrics[period]['max_drawdown']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
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
    events_2015 = events[
        events["date"].between(pd.Timestamp("2015-05-01"), pd.Timestamp("2016-03-31"))
    ] if not events.empty else pd.DataFrame()
    event_rows = "\n".join(
        f"| {pd.Timestamp(row.date).strftime('%Y-%m-%d')} | "
        f"{float(row.exposure):.0%} | {float(row.volatility60):.2%} |"
        for row in events_2015.itertuples(index=False)
    ) or "| 无 | - | - |"
    return f"""# 五资产 ETF 双动量固定风险层 V1

- 数据截止：{latest_date}。
- Alpha、资产池、252日动量和月度Top2完全不变。
- 唯一变化：复用20日组合波动率>45%时降至30%的既有风险层。
- 平均仓位：{risk_summary['average_exposure']:.1%}；降仓日占比：
  {risk_summary['reduced_day_ratio']:.1%}；降仓触发
  {risk_summary['trigger_events']:.0f} 次。
- 与Quality日收益相关性：{quality_correlation:.3f}。

| 阶段 | 原年化 | 风险层年化 | 原最大回撤 | 风险层最大回撤 | 风险层Sharpe |
|---|---:|---:|---:|---:|---:|
{comparison_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 2015回撤期风险事件

| 日期 | 次日目标仓位 | 20日年化波动率 |
|---|---:|---:|
{event_rows}

## 固定门槛

{checks}

最大回撤相对原策略改善：{gate['full_drawdown_improvement']:.2%}。

结论：{'值得进入全新前瞻确认，但不注册生产' if gate['passed'] else '风险层不足以修复，不注册生产'}。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、监控库和原策略结构化运行版本。"""
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
    row = None
    if paths.system_state_path.exists():
        with sqlite3.connect(paths.system_state_path) as connection:
            row = connection.execute(
                """
                SELECT run_fingerprint
                FROM experiment_runs
                WHERE experiment_id = ? AND status = 'SUCCESS'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [base.STRATEGY_ID],
            ).fetchone()
    parts.append(f"base_run:{str(row[0]) if row else 'missing'}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
