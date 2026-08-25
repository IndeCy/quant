"""四只流动性合格科技ETF的周频5日反转研究。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples import a_share_tech_etf_rotation_study as tech
from examples import (
    a_share_tech_etf_weekly_reversal_liquid_feasibility_v2 as feasibility,
)
from examples import global_defensive_equal_study as global_study
from examples.quality_defensive_assets_metrics import build_annual_metrics
from examples.quality_factor_study_support import build_period_metrics
from examples.quality_risk_layer_research import RiskLayerRun
from factors.etf_relative_strength import weekly_signal_dates
from factors.etf_short_term_reversal import (
    build_ranked_targets,
    calculate_weekly_reversal_states,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "a_share_tech_etf_weekly_5d_reversal_v1"
REPORT_PATH = Path("docs/research/a-share-tech-etf-weekly-5d-reversal-v1.md")
MOMENTUM_CONTROL_ID = "tech_etf_weekly_5d_momentum_mirror_control"
EQUAL_CONTROL_ID = "tech_etf_liquid_four_equal_control"
BENCHMARK_CONTROL_ID = "hs300_direct_tech_reversal_control"
STRESS_ID = "a_share_tech_etf_weekly_5d_reversal_30bps"
TOP_N = 2
LOOKBACK_DAYS = 5
SYMBOLS = feasibility.LIQUID_SYMBOLS
NAMES = {symbol: tech.TECH_NAMES[symbol] for symbol in SYMBOLS}
STUDY_START = "20200101"
LOCKED_START = "20240101"
FOLD_KEYS = ("2020_2021", "2022_2023", "2024_latest")
PERIODS = {
    "2020_2021": ("20200101", "20211231"),
    "2022_2023": ("20220101", "20231231"),
    "2024_latest": ("20240101", "LATEST"),
    "locked_test": (LOCKED_START, "LATEST"),
    "full": (STUDY_START, "LATEST"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="A股科技ETF周频5日反转 V1",
    category="allocation_strategy",
    hypothesis=(
        "流动性合格科技ETF中每周持有过去5日最弱的两只，能否捕捉A股科技内部"
        "短期过度反应并战胜静态等权和镜像追涨"
    ),
    definition={
        "feasibility_dependency": feasibility.EXPERIMENT_ID,
        "universe": NAMES,
        "signal": {
            "formula": "close_t/close_t_minus_5-1",
            "ranking": "ascending_weakest_first",
            "signal_time": "weekly_last_trading_day_close",
            "future_data": "forbidden",
        },
        "portfolio": {
            "bottom_n": TOP_N,
            "weighting": "equal_50_50",
            "rebalance": "weekly",
            "cash": 0.0,
            "parameter_grid": False,
        },
        "controls": {
            EQUAL_CONTROL_ID: "same_pool_static_equal",
            MOMENTUM_CONTROL_ID: "same_signal_top_two_mirror",
            BENCHMARK_CONTROL_ID: {tech.BENCHMARK: 1.0},
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 10.0,
            "stress_slippage_bps": 30.0,
            "stamp_tax_rate": 0.0,
        },
        "gate": {
            "full_return_min": 0.08,
            "full_drawdown_floor": -0.50,
            "full_sharpe_min": 0.45,
            "full_calmar_min": 0.15,
            "return_lift_vs_equal_min": 0.01,
            "sharpe_lift_vs_equal_min": 0.05,
            "return_lift_vs_momentum_min": 0.02,
            "positive_excess_vs_hs300": True,
            "positive_folds_min": 2,
            "worst_fold_drawdown_floor": -0.55,
            "median_fold_sharpe_min": 0.35,
            "locked_return_min": 0.08,
            "locked_drawdown_floor": -0.40,
            "locked_sharpe_min": 0.50,
            "positive_years_min": 4,
            "annual_turnover_max": 30.0,
            "stress_return_min": 0.06,
            "stress_sharpe_min": 0.35,
            "worst_day_floor": -0.10,
            "expected_shortfall_95_floor": -0.04,
            "quality_correlation_max": 0.80,
            "selection_share_range": [0.10, 0.45],
        },
        "parameters_fixed_before_backtest": True,
        "promotion_scope": "research_only_never_auto_register",
        "methodology_version": "weekly_reversal_multifold_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized_as_of = min(
        str(as_of_date).replace("-", ""),
        tech.RELIABLE_AS_OF,
    )
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=tech._data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        require_feasibility(paths)
        result, runs, targets, states, holdings = calculate(
            paths,
            normalized_as_of,
        )
        complete_attempt(attempt, result, runs, targets, states, holdings)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[
    dict[str, Any],
    dict[str, RiskLayerRun],
    dict[str, dict[str, dict[str, float]]],
    pd.DataFrame,
    pd.DataFrame,
]:
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        [*SYMBOLS, tech.BENCHMARK],
        start_date=tech.LOAD_START,
        end_date=as_of_date,
    )
    audit = tech.audit_panel(
        panel,
        [*SYMBOLS, tech.BENCHMARK],
        as_of_date,
    )
    if not audit["passed"]:
        raise ValueError(f"科技ETF反转面板审计失败: {audit}")
    signals = [
        date
        for date in weekly_signal_dates(panel.calendar)
        if date >= pd.Timestamp(STUDY_START)
    ]
    states = calculate_weekly_reversal_states(
        panel.adjusted_close,
        signals,
        SYMBOLS,
        lookback_days=LOOKBACK_DAYS,
    )
    reversal_targets, holdings = build_ranked_targets(
        states,
        top_n=TOP_N,
        rank_column="reversal_rank",
    )
    momentum_targets, _ = build_ranked_targets(
        states,
        top_n=TOP_N,
        rank_column="momentum_rank",
    )
    equal_weights = {symbol: 1.0 / len(SYMBOLS) for symbol in SYMBOLS}
    target_sets = {
        EXPERIMENT_ID: reversal_targets,
        STRESS_ID: reversal_targets,
        MOMENTUM_CONTROL_ID: momentum_targets,
        EQUAL_CONTROL_ID: tech._fixed_targets(signals, equal_weights),
        BENCHMARK_CONTROL_ID: tech._fixed_targets(
            signals,
            {tech.BENCHMARK: 1.0},
        ),
    }
    benchmark = tech._benchmark_curve(panel)
    runs = {
        name: tech._run(
            name,
            targets,
            panel,
            benchmark,
            slippage_bps=30.0 if name == STRESS_ID else 10.0,
        )
        for name, targets in target_sets.items()
    }
    periods = {
        name: (start, panel.latest_common_date if end == "LATEST" else end)
        for name, (start, end) in PERIODS.items()
    }
    metrics = build_period_metrics(
        {name: run.result for name, run in runs.items()},
        benchmark,
        periods,
    )
    annual_all = build_annual_metrics(runs, benchmark, panel.latest_common_date)
    annual = {
        year: item
        for year, item in annual_all[EXPERIMENT_ID].items()
        if year >= STUDY_START[:4]
    }
    diagnostics = build_diagnostics(
        paths,
        runs[EXPERIMENT_ID],
        holdings,
    )
    gate = evaluate_gate(metrics, annual, diagnostics, audit)
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": panel.latest_common_date,
        "data_audit": audit,
        "period_metrics": metrics[EXPERIMENT_ID],
        "full_comparison": {
            name: values["full"]
            for name, values in metrics.items()
            if name != STRESS_ID
        },
        "annual_metrics": annual,
        "diagnostics": diagnostics,
        "latest_holdings": latest_holdings(holdings),
        "gate": gate,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, runs, target_sets, states, holdings


def build_diagnostics(
    paths: RuntimePaths,
    run: RiskLayerRun,
    holdings: pd.DataFrame,
) -> dict[str, Any]:
    nav = run.result.daily_values.loc[STUDY_START:].astype(float)
    returns = nav.pct_change().dropna()
    threshold = float(returns.quantile(0.05))
    counts = holdings["symbol"].value_counts(normalize=True)
    selection_share = {
        symbol: float(counts.get(symbol, 0.0))
        for symbol in SYMBOLS
    }
    return {
        "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)),
        "worst_day": float(returns.min()),
        "expected_shortfall_95": float(
            returns[returns.le(threshold)].mean()
        ),
        "quality_correlation": global_study.load_quality_correlation(paths, run),
        "selection_share": selection_share,
    }


def evaluate_gate(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, float]],
    diagnostics: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    candidate = metrics[EXPERIMENT_ID]
    full = candidate["full"]
    locked = candidate["locked_test"]
    equal = metrics[EQUAL_CONTROL_ID]["full"]
    momentum = metrics[MOMENTUM_CONTROL_ID]["full"]
    benchmark = metrics[BENCHMARK_CONTROL_ID]["full"]
    stress = metrics[STRESS_ID]["full"]
    folds = [candidate[key] for key in FOLD_KEYS]
    positive_years = sum(
        item["annualized_return"] > 0 for item in annual.values()
    )
    shares = list(diagnostics["selection_share"].values())
    checks = {
        "data_audit": bool(audit["passed"]),
        "full_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_drawdown_within_50pct": full["max_drawdown"] >= -0.50,
        "full_sharpe_at_least_045": full["sharpe"] >= 0.45,
        "full_calmar_at_least_015": full["calmar"] >= 0.15,
        "return_lift_vs_equal_at_least_1pct": (
            full["annualized_return"] - equal["annualized_return"] >= 0.01
        ),
        "sharpe_lift_vs_equal_at_least_005": (
            full["sharpe"] - equal["sharpe"] >= 0.05
        ),
        "return_lift_vs_momentum_at_least_2pct": (
            full["annualized_return"] - momentum["annualized_return"] >= 0.02
        ),
        "positive_excess_vs_hs300": (
            full["annualized_return"] > benchmark["annualized_return"]
        ),
        "at_least_two_positive_folds": (
            sum(item["annualized_return"] > 0 for item in folds) >= 2
        ),
        "worst_fold_drawdown_within_55pct": (
            min(item["max_drawdown"] for item in folds) >= -0.55
        ),
        "median_fold_sharpe_at_least_035": (
            float(pd.Series([item["sharpe"] for item in folds]).median())
            >= 0.35
        ),
        "locked_return_at_least_8pct": locked["annualized_return"] >= 0.08,
        "locked_drawdown_within_40pct": locked["max_drawdown"] >= -0.40,
        "locked_sharpe_at_least_050": locked["sharpe"] >= 0.50,
        "at_least_four_positive_years": positive_years >= 4,
        "annual_turnover_below_30x": full["annual_turnover"] <= 30.0,
        "stress_return_at_least_6pct": stress["annualized_return"] >= 0.06,
        "stress_sharpe_at_least_035": stress["sharpe"] >= 0.35,
        "worst_day_within_10pct": diagnostics["worst_day"] >= -0.10,
        "expected_shortfall_95_within_4pct": (
            diagnostics["expected_shortfall_95"] >= -0.04
        ),
        "quality_correlation_at_most_080": (
            abs(diagnostics["quality_correlation"]) <= 0.80
        ),
        "selection_share_between_10_and_45pct": (
            bool(shares)
            and min(shares) >= 0.10
            and max(shares) <= 0.45
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_years": positive_years,
    }


def latest_holdings(holdings: pd.DataFrame) -> list[dict[str, Any]]:
    latest = str(holdings["signal_date"].max())
    rows = holdings[holdings["signal_date"].eq(latest)]
    return [
        {
            "symbol": str(row.symbol),
            "name": NAMES[str(row.symbol)],
            "target_weight": float(row.target_weight),
            "return_5d": float(row.return_5d),
        }
        for row in rows.sort_values("rank").itertuples(index=False)
    ]


def require_feasibility(paths: RuntimePaths) -> None:
    detail = SystemRepository(paths.system_state_path).load_experiment_detail(
        feasibility.EXPERIMENT_ID
    )
    latest = detail.get("latest_run") if detail else None
    if not latest or latest.get("status") != "SUCCESS":
        raise RuntimeError("科技ETF反转流动性门禁尚未成功完成")
    if latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("科技ETF反转流动性门禁未通过")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    runs: dict[str, RiskLayerRun],
    targets: dict[str, dict[str, dict[str, float]]],
    states: pd.DataFrame,
    holdings: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    nav_path = attempt.output_dir / "daily_nav_comparison.csv"
    pd.DataFrame(
        {
            name: run.result.daily_values / float(run.result.daily_values.iloc[0])
            for name, run in runs.items()
        }
    ).rename_axis("trade_date").reset_index().to_csv(nav_path, index=False)
    targets_path = attempt.output_dir / "weekly_targets.csv"
    pd.DataFrame(
        [
            {
                "strategy_id": name,
                "signal_date": date,
                "symbol": symbol,
                "target_weight": weight,
            }
            for name, strategy_targets in targets.items()
            for date, weights in strategy_targets.items()
            for symbol, weight in weights.items()
        ]
    ).to_csv(targets_path, index=False)
    states_path = attempt.output_dir / "weekly_states.csv"
    states.to_csv(states_path, index=False)
    holdings_path = attempt.output_dir / "weekly_holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    diagnostics_path = attempt.output_dir / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(
            {
                "data_audit": result["data_audit"],
                "diagnostics": result["diagnostics"],
                "gate": result["gate"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    failed = [
        name for name, value in result["gate"]["checks"].items() if not value
    ]
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "科技ETF周频5日反转通过冻结门槛，仅允许研究级观察"
            if passed
            else f"科技ETF周频5日反转失败（{', '.join(failed)}），不注册"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "反转研究报告"),
            ExperimentArtifact("daily_nav", nav_path, "候选与对照净值"),
            ExperimentArtifact("weekly_targets", targets_path, "周频目标"),
            ExperimentArtifact("weekly_states", states_path, "周频信号"),
            ExperimentArtifact("weekly_holdings", holdings_path, "周频持仓"),
            ExperimentArtifact("diagnostics", diagnostics_path, "门槛诊断"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['annual_turnover']:.2f}x |"
        for name, item in result["period_metrics"].items()
    )
    comparisons = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    holdings = "\n".join(
        f"| {item['symbol']} | {item['name']} | "
        f"{item['target_weight']:.1%} | {item['return_5d']:.2%} |"
        for item in result["latest_holdings"]
    )
    shares = "\n".join(
        f"| {symbol} | {NAMES[symbol]} | {share:.1%} |"
        for symbol, share in result["diagnostics"]["selection_share"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# A股科技ETF周频5日反转 V1

- 固定四只流动性合格科技ETF；周末按过去5日收益从弱到强排名。
- 持有最弱两只、各50%；下一交易日M0执行，基础10bps、压力30bps。
- 不做窗口、Top-N、权重或频率网格。
- 数据共同截止：{result['latest_date']}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{periods}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{comparisons}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 最新目标

| 代码 | 名称 | 权重 | 信号日5日收益 |
|---|---|---:|---:|
{holdings}

## 选择覆盖

| 代码 | 名称 | 入选占比 |
|---|---|---:|
{shares}

- 年化波动：{result['diagnostics']['annualized_volatility']:.2%}
- 最差单日：{result['diagnostics']['worst_day']:.2%}
- 95% Expected Shortfall：{result['diagnostics']['expected_shortfall_95']:.2%}
- 与Quality日收益相关性：{result['diagnostics']['quality_correlation']:.3f}

## 冻结门槛

{checks}

结论：{'通过冻结门槛，仅允许研究级前向观察' if result['gate']['passed'] else '未通过冻结门槛，归档且不注册'}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=tech.RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
