"""Quality Balanced Value 的截面市值残差评分研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.benchmark_series import load_adjusted_fund_curve
from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_feature_bars,
    load_month_end_signal_dates,
    load_trading_calendar,
    materialize_market_features,
)
from data.quality_financial import (
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    attach_report_adjustment_factors,
    build_quality_value_lowvol_candidates,
)
from examples.quality_balanced_value_buffered_study import (
    BASELINE_ID,
    STUDY_START,
    TOP_N,
    _annual_metrics,
    _data_version,
    _equal_weight_targets,
    _financial_paths,
    _run_candidate,
    _score_candidates,
)
from examples.quality_balanced_value_size_neutral_study import (
    PERIODS,
    _build_size_universe,
    _style_residual,
)
from examples.quality_factor_study_support import build_period_metrics
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
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


EXPERIMENT_ID = "quality_balanced_value_size_residual_v1"
REPORT_PATH = Path("docs/research/quality-balanced-value-size-residual-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality Balanced Value 截面市值残差 V1",
    category="portfolio_strategy",
    hypothesis="逐月剔除Quality综合分数的线性对数市值成分后，能否降低中盘共同Beta并保留独立Alpha",
    definition={
        "source_strategy": {
            "strategy_id": "quality_balanced_value_v1",
            "raw_factors_unchanged": True,
            "universe_unchanged": True,
            "base_score_unchanged": True,
        },
        "size_proxy": {
            "formula": "signal_date_raw_close_times_latest_visible_total_share",
            "visibility": "balance_f_ann_date_lte_signal_date",
            "transform": "natural_log",
        },
        "residualization": {
            "cross_section": "each_signal_date",
            "model": "base_factor_score_equals_intercept_plus_beta_log_market_cap",
            "selection_score": "ols_residual",
            "fit_universe": "all_eligible_scored_candidates",
            "no_locked_period_parameter": True,
        },
        "portfolio": {
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly",
        },
        "risk_overlay": {
            "scheme": "GRID",
            "window": 20,
            "volatility_threshold": 0.45,
            "reduced_exposure": 0.30,
            "frequency": "daily",
            "unchanged": True,
        },
        "execution": {
            "model": "M0",
            "lag": 1,
            "adjust": "qfq",
            "base_slippage_bps": 5.0,
            "stress_slippage_bps": 20.0,
        },
        "style_residual": {
            "style": "510500_minus_510300_annual",
            "validation_train": [2015, 2016, 2017, 2018],
            "validation_apply": [2019, 2020, 2021],
            "locked_train": list(range(2015, 2022)),
            "locked_apply": list(range(2022, 2027)),
            "beta_has_intercept": True,
            "residual_keeps_intercept": True,
        },
        "frozen_gate": {
            "style_beta_reduction": 0.30,
            "walk_forward_residual_all_checks": True,
            "full_annual_return": 0.08,
            "full_sharpe": 0.55,
            "full_drawdown": -0.30,
            "locked_annual_return": 0.06,
            "locked_sharpe": 0.40,
            "annual_turnover_vs_baseline_max": 1.25,
            "stress_annual_return": 0.07,
            "market_cap_coverage": 0.95,
            "median_abs_residual_size_correlation": 0.02,
        },
        "decision": "research_only_never_auto_register",
        "methodology_version": "monthly_cross_section_log_size_ols_residual_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记固定残差定义，再读取大表和执行回测。"""
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
    """同一Quality分数分别做原始Top20和市值残差Top20。"""
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
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_quality_signal_date_table(connection, signal_dates)
        attach_quality_financial_databases(connection, _financial_paths(paths))
        materialize_quality_financial_asof(connection, annual_only=True)
        raw_candidates = load_annual_quality_candidates(connection)
        filtered = apply_quality_universe_filters(raw_candidates)
        adjusted = attach_report_adjustment_factors(connection, filtered)
        candidates, corporate_action_audit = build_quality_value_lowvol_candidates(adjusted)
        scores = _score_candidates(candidates)
        size_universe = _build_size_universe(connection, signal_dates)
        selections, holdings, residual_diagnostics = _build_selections(
            scores,
            size_universe,
        )
        symbols = sorted(
            {
                symbol
                for mapping in selections.values()
                for selected in mapping.values()
                for symbol in selected
            }
        )
        bars = load_feature_bars(connection, symbols)
        calendar = load_trading_calendar(connection)
    finally:
        connection.close()

    hs300 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510300.SH",
        end_date=latest_date,
    )
    csi500 = load_adjusted_fund_curve(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        "510500.SH",
        end_date=latest_date,
    )
    targets = {
        strategy_id: _equal_weight_targets(mapping)
        for strategy_id, mapping in selections.items()
    }
    runs = {
        strategy_id: _run_candidate(
            strategy_id,
            target,
            bars,
            calendar,
            hs300,
            slippage_bps=5.0,
        )
        for strategy_id, target in targets.items()
    }
    stress_run = _run_candidate(
        f"{EXPERIMENT_ID}_20bps",
        targets[EXPERIMENT_ID],
        bars,
        calendar,
        hs300,
        slippage_bps=20.0,
    )
    periods = {
        name: (start, latest_date if end == "latest" else min(end, latest_date))
        for name, (start, end) in PERIODS.items()
        if start <= latest_date
    }
    period_metrics = build_period_metrics(
        {strategy_id: run.result for strategy_id, run in runs.items()},
        hs300,
        periods,
    )
    annual_metrics = _annual_metrics(runs, hs300, latest_date)
    stress_metrics = build_period_metrics(
        {"20bps": stress_run.result},
        hs300,
        {"full": (STUDY_START, latest_date)},
    )["20bps"]["full"]
    style_residual = _style_residual(runs, hs300, csi500)
    gate = evaluate_gate(
        candidate=period_metrics[EXPERIMENT_ID],
        baseline=period_metrics[BASELINE_ID],
        stress=stress_metrics,
        candidate_residual=style_residual[EXPERIMENT_ID],
        baseline_residual=style_residual[BASELINE_ID],
        residual_diagnostics=residual_diagnostics,
    )
    latest_holdings = holdings[
        holdings["strategy_id"].eq(EXPERIMENT_ID)
        & holdings["signal_date"].eq(holdings["signal_date"].max())
    ].copy()
    result = {
        "strategy_id": EXPERIMENT_ID,
        "latest_date": latest_date,
        "gate": gate,
        "decision": (
            "HISTORICAL_STYLE_RESIDUAL_GATE_PASSED_FORWARD_CONFIRMATION_ONLY"
            if gate["passed"]
            else "REJECTED_NO_PRODUCTION_CHANGE"
        ),
        "period_metrics": period_metrics,
        "annual_metrics": annual_metrics,
        "stress_20bps_metrics": stress_metrics,
        "style_residual": style_residual,
        "residual_diagnostics": residual_diagnostics,
        "corporate_action_audit": {
            "checked_rows": corporate_action_audit.checked_rows,
            "excluded_rows": corporate_action_audit.excluded_rows,
            "missing_rows": corporate_action_audit.missing_rows,
        },
        "latest_holdings": latest_holdings[
            [
                "signal_date",
                "symbol",
                "name",
                "rank",
                "factor_score",
                "size_residual_score",
                "market_cap_percentile",
            ]
        ].to_dict("records"),
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _build_selections(
    scores: pd.DataFrame,
    size_universe: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame, dict[str, float]]:
    """逐月OLS剔除对数市值斜率，再用残差稳定排序Top20。"""
    enriched = scores.merge(
        size_universe,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    enriched["log_market_cap"] = np.log(
        pd.to_numeric(enriched["market_cap_proxy"], errors="coerce")
    )
    baseline, baseline_holdings = build_topn_selections(
        enriched,
        "factor_score",
        TOP_N,
    )
    residual_frames: list[pd.DataFrame] = []
    raw_correlations: list[float] = []
    residual_correlations: list[float] = []
    slopes: list[float] = []
    covered_rows = 0
    for signal_date, group in enriched.groupby("signal_date", sort=True):
        valid = group.dropna(
            subset=["factor_score", "log_market_cap"]
        ).copy()
        covered_rows += len(valid)
        if len(valid) < TOP_N:
            raise ValueError(f"市值残差有效候选不足: {signal_date}={len(valid)}")
        design = np.column_stack(
            [
                np.ones(len(valid)),
                valid["log_market_cap"].to_numpy(dtype=float),
            ]
        )
        intercept, slope = np.linalg.lstsq(
            design,
            valid["factor_score"].to_numpy(dtype=float),
            rcond=None,
        )[0]
        valid["size_residual_score"] = (
            valid["factor_score"]
            - intercept
            - slope * valid["log_market_cap"]
        )
        raw_correlations.append(
            float(valid["factor_score"].corr(valid["log_market_cap"]))
        )
        residual_correlations.append(
            float(valid["size_residual_score"].corr(valid["log_market_cap"]))
        )
        slopes.append(float(slope))
        valid["signal_date"] = str(signal_date)
        residual_frames.append(valid)
    residual_scores = pd.concat(residual_frames, ignore_index=True)
    residual, residual_holdings = build_topn_selections(
        residual_scores,
        "size_residual_score",
        TOP_N,
    )
    baseline_holdings["strategy_id"] = BASELINE_ID
    residual_holdings["strategy_id"] = EXPERIMENT_ID
    diagnostics = {
        "market_cap_coverage": covered_rows / max(len(enriched), 1),
        "median_raw_score_size_correlation": float(
            pd.Series(raw_correlations).median()
        ),
        "median_residual_score_size_correlation": float(
            pd.Series(residual_correlations).median()
        ),
        "median_size_slope": float(pd.Series(slopes).median()),
        "latest_holding_median_market_cap_percentile": float(
            residual_holdings[
                residual_holdings["signal_date"].eq(
                    residual_holdings["signal_date"].max()
                )
            ]["market_cap_percentile"].median()
        ),
    }
    return (
        {BASELINE_ID: baseline, EXPERIMENT_ID: residual},
        pd.concat([baseline_holdings, residual_holdings], ignore_index=True),
        diagnostics,
    )


def evaluate_gate(
    *,
    candidate: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    stress: dict[str, float],
    candidate_residual: dict[str, Any],
    baseline_residual: dict[str, Any],
    residual_diagnostics: dict[str, float],
) -> dict[str, Any]:
    """统计中性化与收益、回撤、换手必须同时成立。"""
    full = candidate["full"]
    locked = candidate["locked_test"]
    baseline_full = baseline["full"]
    baseline_beta = abs(float(baseline_residual["locked_beta"]))
    candidate_beta = abs(float(candidate_residual["locked_beta"]))
    beta_reduction = (
        1.0 - candidate_beta / baseline_beta
        if baseline_beta > 0
        else 0.0
    )
    checks = {
        "locked_style_beta_reduced_by_at_least_30pct": beta_reduction >= 0.30,
        "walk_forward_style_residual_gate_passed": bool(
            candidate_residual["gate_passed"]
        ),
        "full_annual_return_at_least_8pct": full["annualized_return"] >= 0.08,
        "full_sharpe_at_least_055": full["sharpe"] >= 0.55,
        "full_drawdown_within_30pct": full["max_drawdown"] >= -0.30,
        "locked_annual_return_at_least_6pct": locked["annualized_return"] >= 0.06,
        "locked_sharpe_at_least_040": locked["sharpe"] >= 0.40,
        "annual_turnover_not_over_baseline_125pct": (
            full["annual_turnover"] <= baseline_full["annual_turnover"] * 1.25
        ),
        "stress_20bps_annual_return_at_least_7pct": (
            stress["annualized_return"] >= 0.07
        ),
        "market_cap_coverage_at_least_95pct": (
            residual_diagnostics["market_cap_coverage"] >= 0.95
        ),
        "median_abs_residual_size_correlation_at_most_002": (
            abs(
                residual_diagnostics[
                    "median_residual_score_size_correlation"
                ]
            )
            <= 0.02
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "locked_style_beta_reduction": beta_reduction,
    }


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
            "截面市值残差通过走步残差与交易门槛，仅进入冻结前瞻确认"
            if passed
            else "截面市值残差未通过全部门槛，不修改现有策略或生产调度"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "市值残差研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新市值残差持仓"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for strategy_id in (BASELINE_ID, EXPERIMENT_ID):
        for period in (
            "2015_2017",
            "2018_2020",
            "2021_2023",
            "2024_latest",
            "locked_test",
            "full",
        ):
            item = result["period_metrics"][strategy_id][period]
            rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['excess_return']:.2%} | {item['annual_turnover']:.2f}x |"
            )
    residual_rows = "\n".join(
        f"| {strategy_id} | {item['validation_beta']:.3f} | "
        f"{item['locked_beta']:.3f} | {item['validation_mean_residual']:.2%} | "
        f"{item['locked_mean_residual']:.2%} | "
        f"{item['locked_positive_year_share']:.1%} | "
        f"{item['locked_residual_information_ratio']:.3f} | "
        f"{item['locked_worst_residual']:.2%} | "
        f"{'PASS' if item['gate_passed'] else 'FAIL'} |"
        for strategy_id, item in result["style_residual"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    diagnostics = result["residual_diagnostics"]
    stress = result["stress_20bps_metrics"]
    return f"""# Quality Balanced Value 截面市值残差 V1

- 数据截止：{result['latest_date']}。
- 原始Quality与估值因子、股票池、风险层和M0保持不变。
- 每月在完整候选池回归 `factor_score ~ 1 + log(可见市值)`，
  仅使用残差做Top20排名。
- 本研究不修改生产策略或调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 截面中性化诊断

- 市值覆盖：{diagnostics['market_cap_coverage']:.2%}。
- 原分数与对数市值相关中位数：
  {diagnostics['median_raw_score_size_correlation']:.4f}。
- 残差分数与对数市值相关中位数：
  {diagnostics['median_residual_score_size_correlation']:.6f}。
- 月度市值斜率中位数：{diagnostics['median_size_slope']:.6f}。
- 最新持仓市值分位中位数：
  {diagnostics['latest_holding_median_market_cap_percentile']:.2%}。

## 走步中盘风格残差

| 策略 | 验证Beta | 锁定Beta | 验证残差 | 锁定残差 | 锁定正残差年 | 锁定IR | 最差锁定年 | 门槛 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{residual_rows}

- 候选相对基线锁定Beta降幅：
  {result['gate']['locked_style_beta_reduction']:.2%}。
- 20bps压力年化/Sharpe：
  {stress['annualized_return']:.2%} / {stress['sharpe']:.3f}。

## 预注册门槛

{checks}

结论：{result['decision']}。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
