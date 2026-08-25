"""跨资产双动量叠加既有分级风险恢复状态机的固定研究。"""

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
from examples import cross_asset_dual_momentum_risk_study as binary
from examples import cross_asset_dual_momentum_study as base
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun, run_risk_layer_backtest
from examples.quality_value_lowvol_risk_recovery_study import StatefulRecoveryController
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


STRATEGY_ID = "cross_asset_dual_momentum_stateful_risk_v1"
REPORT_PATH = Path("docs/research/cross-asset-dual-momentum-stateful-risk-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="五资产ETF双动量分级风险恢复 V1",
    category="risk_attribution",
    hypothesis="既有分级恢复状态机能否保留风险保护并消除二元仓位开关抖动",
    definition={
        "base_strategy": base.STRATEGY_ID,
        "alpha_change": "none",
        "risk_trigger": {
            "volatility_window": 20,
            "threshold": 0.45,
            "reduced_exposure": 0.30,
        },
        "recovery": {
            "source": "existing_stateful_recovery_controller",
            "steps": [0.50, 0.70, 1.00],
            "stable_days": 3,
            "minimum_drawdown_recovery": 0.02,
            "critical_state_blocks_recovery": True,
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
            "execution_cost_vs_binary_max_ratio": 1.10,
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
    """登记固定研究指纹后执行状态型风险层回测。"""
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
        result, run, holdings, controller = _calculate(paths, as_of_date)
        _complete_attempt(attempt, result, run, holdings, controller)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    RiskLayerRun,
    pd.DataFrame,
    StatefulRecoveryController,
]:
    """复用原始月度目标，仅替换风险恢复方式。"""
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
    controller = StatefulRecoveryController()
    run = run_risk_layer_backtest(
        STRATEGY_ID,
        "FIXED",
        targets,
        panel.bars,
        panel.calendar,
        benchmark,
        base._execution_model(),
        vol_window=20,
        exposure_controller=controller,
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
    base_result = load_result(paths, base.STRATEGY_ID)
    binary_result = load_result(paths, binary.STRATEGY_ID)
    gate = evaluate_gate(
        metrics,
        quality_correlation,
        base_result["period_metrics"],
        binary_result["period_metrics"],
    )
    annual = base.build_annual_metrics(run, benchmark, panel.latest_common_date)
    risk_summary = build_risk_summary(run, controller)
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
            risk_summary,
            base_result["period_metrics"],
            binary_result["period_metrics"],
            controller.transitions,
            panel.latest_common_date,
        ),
        encoding="utf-8",
    )
    return (
        {
            "strategy_id": STRATEGY_ID,
            "base_strategy_id": base.STRATEGY_ID,
            "binary_risk_strategy_id": binary.STRATEGY_ID,
            "latest_date": panel.latest_common_date,
            "period_metrics": metrics,
            "annual_metrics": annual,
            "quality_return_correlation": quality_correlation,
            "risk_summary": risk_summary,
            "risk_transitions": controller.transitions,
            "gate": gate,
            "base_period_metrics": base_result["period_metrics"],
            "binary_period_metrics": binary_result["period_metrics"],
            "latest_holdings": latest_holdings.to_dict("records"),
            "promotion_allowed": False,
            "promotion_block_reason": (
                "状态机由完整历史回撤归因触发研究，必须从新数据前瞻验证"
            ),
            "report_path": str(report_path),
            "reused": False,
        },
        run,
        holdings,
        controller,
    )


def load_result(paths: RuntimePaths, experiment_id: str) -> dict[str, Any]:
    """读取指定实验最新结构化成功结果。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        row = connection.execute(
            """
            SELECT metrics_json
            FROM experiment_runs
            WHERE experiment_id = ? AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [experiment_id],
        ).fetchone()
    if row is None:
        raise ValueError(f"缺少结构化实验基线: {experiment_id}")
    result = json.loads(str(row[0] or "{}"))
    if "period_metrics" not in result:
        raise ValueError(f"实验缺少区间指标: {experiment_id}")
    return result


def evaluate_gate(
    metrics: dict[str, dict[str, float]],
    quality_correlation: float,
    base_metrics: dict[str, dict[str, float]],
    binary_metrics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """沿用原门槛，并验证回撤改善与执行成本。"""
    original = base.evaluate_gate(metrics, quality_correlation)
    improvement = (
        metrics["full"]["max_drawdown"]
        - base_metrics["full"]["max_drawdown"]
    )
    binary_cost = binary_metrics["full"]["execution_cost_impact"]
    checks = {
        **original["checks"],
        "full_drawdown_improves_base_by_15pct": improvement >= 0.15,
        "execution_cost_not_worse_binary_10pct": (
            metrics["full"]["execution_cost_impact"] <= binary_cost * 1.10
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "full_drawdown_improvement": float(improvement),
        "execution_cost_vs_binary_ratio": float(
            metrics["full"]["execution_cost_impact"] / binary_cost
        ),
    }


def build_risk_summary(
    run: RiskLayerRun,
    controller: StatefulRecoveryController,
) -> dict[str, float]:
    """统计状态型风险层的仓位、限仓时间和迁移次数。"""
    exposure = run.exposure.dropna()
    return {
        "average_exposure": float(exposure.mean()),
        "reduced_trading_days": float(exposure.lt(1.0).sum()),
        "reduced_day_ratio": float(exposure.lt(1.0).mean()),
        "transition_count": float(len(controller.transitions)),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    run: RiskLayerRun,
    holdings: pd.DataFrame,
    controller: StatefulRecoveryController,
) -> None:
    """归档状态迁移、净值与原始月度目标。"""
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
    transitions_path = attempt.output_dir / "risk_transitions.csv"
    pd.DataFrame(controller.transitions).to_csv(transitions_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "分级恢复通过固定研究门槛，只允许进入前瞻确认"
            if passed
            else "分级恢复仍未通过门槛，终止跨资产双动量研究"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "分级恢复研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "策略净值和目标仓位"),
            ExperimentArtifact("monthly_targets", holdings_path, "原始月度目标"),
            ExperimentArtifact("risk_transitions", transitions_path, "风险状态迁移"),
        ],
    )


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    risk_summary: dict[str, float],
    base_metrics: dict[str, dict[str, float]],
    binary_metrics: dict[str, dict[str, float]],
    transitions: list[dict[str, Any]],
    latest_date: str,
) -> str:
    """生成三方案对照与状态迁移报告。"""
    rows = "\n".join(
        f"| {period} | {base_metrics[period]['annualized_return']:.2%} | "
        f"{binary_metrics[period]['annualized_return']:.2%} | "
        f"{item['annualized_return']:.2%} | "
        f"{base_metrics[period]['max_drawdown']:.2%} | "
        f"{binary_metrics[period]['max_drawdown']:.2%} | "
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
    transition_rows = "\n".join(
        f"| {item['date']} | {item['from_exposure']:.0%} | "
        f"{item['to_exposure']:.0%} | {item['reason']} |"
        for item in transitions
        if "20150501" <= str(item["date"]) <= "20160331"
    ) or "| 无 | - | - | - |"
    return f"""# 五资产 ETF 双动量分级风险恢复 V1

- 数据截止：{latest_date}。
- Alpha和月度目标不变，只把二元恢复替换为现有分级恢复状态机。
- 平均仓位：{risk_summary['average_exposure']:.1%}；限仓日占比：
  {risk_summary['reduced_day_ratio']:.1%}；状态迁移
  {risk_summary['transition_count']:.0f} 次。
- 与Quality日收益相关性：{quality_correlation:.3f}。

| 阶段 | 原年化 | 二元风险年化 | 分级恢复年化 | 原回撤 | 二元风险回撤 | 分级恢复回撤 | 分级Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
{rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 2015风险迁移

| 日期 | 原仓位 | 新仓位 | 原因 |
|---|---:|---:|---|
{transition_rows}

## 固定门槛

{checks}

- 相对无风险层回撤改善：{gate['full_drawdown_improvement']:.2%}。
- 执行成本/二元风险层：{gate['execution_cost_vs_binary_ratio']:.2f}x。

结论：{'只进入全新前瞻确认，不注册生产' if gate['passed'] else '终止该研究方向，不再调参'}。
"""


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、Quality历史和两个结构化基线指纹。"""
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
    with sqlite3.connect(paths.system_state_path) as connection:
        for experiment_id in [base.STRATEGY_ID, binary.STRATEGY_ID]:
            row = connection.execute(
                """
                SELECT run_fingerprint
                FROM experiment_runs
                WHERE experiment_id = ? AND status = 'SUCCESS'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                [experiment_id],
            ).fetchone()
            parts.append(
                f"{experiment_id}:{str(row[0]) if row else 'missing'}"
            )
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
