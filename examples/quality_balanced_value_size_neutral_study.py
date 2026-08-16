"""Quality Balanced Value 的市值分层中性组合研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

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
from examples.factor_zoo_walk_forward_residual_metrics import (
    evaluate_single_candidate,
)
from examples.quality_balanced_value_buffered_study import (
    BASELINE_ID,
    STUDY_START,
    TOP_N,
    _annual_metrics,
    _calendar_returns,
    _data_version,
    _equal_weight_targets,
    _financial_paths,
    _run_candidate,
    _score_candidates,
)
from examples.quality_factor_study_support import build_period_metrics
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


EXPERIMENT_ID = "quality_balanced_value_size_neutral_v1"
REPORT_PATH = Path("docs/research/quality-balanced-value-size-neutral-v1.md")
BUCKET_COUNT = 4
PER_BUCKET = TOP_N // BUCKET_COUNT
LOCKED_START = "20220101"
PERIODS = {
    "2015_2017": ("20150101", "20171231"),
    "2018_2020": ("20180101", "20201231"),
    "2021_2023": ("20210101", "20231231"),
    "2024_latest": ("20240101", "latest"),
    "locked_test": (LOCKED_START, "latest"),
    "full": (STUDY_START, "latest"),
}
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="Quality Balanced Value 市值分层中性 V1",
    category="portfolio_strategy",
    hypothesis="冻结Quality Alpha后，四市值分位等名额能否降低中盘共同Beta并保留样本外残差收益",
    definition={
        "source_strategy": {
            "strategy_id": "quality_balanced_value_v1",
            "factors_unchanged": True,
            "universe_unchanged": True,
            "score_unchanged": True,
        },
        "size_proxy": {
            "formula": "signal_date_raw_close_times_latest_visible_total_share",
            "visibility": "balance_f_ann_date_lte_signal_date",
            "percentile_universe": "same_standard_investable_universe",
        },
        "portfolio": {
            "bucket_count": BUCKET_COUNT,
            "per_bucket": PER_BUCKET,
            "top_n": TOP_N,
            "weight": "equal",
            "rebalance": "monthly",
            "fallback": "highest_score_only_if_bucket_has_fewer_than_quota",
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
            "locked_residual_all_checks": True,
            "full_annual_return": 0.08,
            "full_sharpe": 0.55,
            "full_drawdown": -0.30,
            "locked_annual_return": 0.06,
            "locked_sharpe": 0.40,
            "annual_turnover_vs_baseline_max": 1.15,
            "stress_annual_return": 0.07,
            "size_coverage": 0.95,
        },
        "decision": "research_only_never_auto_register",
        "methodology_version": "four_size_bucket_equal_quota_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记研究定义后才物化财务与市值点时截面。"""
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
    """共享冻结分数，对照普通Top20与四市值分位Top20。"""
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
        selections, holdings, size_diagnostics = _build_selections(
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
        size_diagnostics=size_diagnostics,
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
        "size_diagnostics": size_diagnostics,
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
                "market_cap_percentile",
                "size_bucket",
            ]
        ].to_dict("records"),
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _build_size_universe(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """按信号日可见总股本构造同日标准可投池市值分位。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE size_neutral_dates(signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO size_neutral_dates VALUES (?)",
        [(date,) for date in signal_dates],
    )
    return connection.execute(
        """
        WITH share_ranked AS (
            SELECT
                d.signal_date,
                b.ts_code AS symbol,
                CAST(b.total_share AS DOUBLE) AS total_share,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, b.ts_code
                    ORDER BY b.end_date DESC, b.f_ann_date DESC,
                             b.update_flag DESC
                ) AS rn
            FROM size_neutral_dates d
            JOIN balance_db.default_table b
              ON b.f_ann_date <= d.signal_date
            WHERE b.f_ann_date IS NOT NULL
              AND b.total_share > 0
        ),
        investable AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                f.raw_close * s.total_share AS market_cap_proxy
            FROM features f
            JOIN share_ranked s
              ON f.trade_date = s.signal_date
             AND f.symbol = s.symbol
             AND s.rn = 1
            JOIN stock_basic sb ON f.symbol = sb.ts_code
            WHERE f.trade_date IN (SELECT signal_date FROM size_neutral_dates)
              AND f.st_name IS NULL
              AND NOT f.is_suspended
              AND f.amount > f.amount_p20
              AND f.volume > 0
              AND f.raw_close > 0
              AND sb.list_date IS NOT NULL
              AND STRPTIME(f.trade_date, '%Y%m%d')
                  >= STRPTIME(sb.list_date, '%Y%m%d') + INTERVAL 3 YEAR
              AND (
                  sb.delist_date IS NULL
                  OR sb.delist_date > f.trade_date
              )
        )
        SELECT
            signal_date,
            symbol,
            market_cap_proxy,
            PERCENT_RANK() OVER(
                PARTITION BY signal_date
                ORDER BY market_cap_proxy
            ) AS market_cap_percentile
        FROM investable
        ORDER BY signal_date, symbol
        """
    ).fetchdf()


def _build_selections(
    scores: pd.DataFrame,
    size_universe: pd.DataFrame,
) -> tuple[dict[str, dict[str, list[str]]], pd.DataFrame, dict[str, float]]:
    """普通Top20与四市值分位各5只使用完全相同的Alpha分数。"""
    enriched = scores.merge(
        size_universe,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    enriched["size_bucket"] = (
        pd.to_numeric(enriched["market_cap_percentile"], errors="coerce")
        .mul(BUCKET_COUNT)
        .clip(upper=BUCKET_COUNT - 1)
        .apply(lambda value: int(value) if pd.notna(value) else -1)
    )
    baseline: dict[str, list[str]] = {}
    neutral: dict[str, list[str]] = {}
    holdings: list[pd.DataFrame] = []
    complete_bucket_months = 0
    total_months = 0
    covered_rows = int(enriched["market_cap_percentile"].notna().sum())
    for signal_date, group in enriched.groupby("signal_date", sort=True):
        total_months += 1
        ranked = group.sort_values(
            ["factor_score", "symbol"],
            ascending=[False, True],
            kind="stable",
        ).copy()
        plain = ranked.head(TOP_N).copy()
        plain["rank"] = range(1, len(plain) + 1)
        plain["strategy_id"] = BASELINE_ID
        baseline[str(signal_date)] = plain["symbol"].astype(str).tolist()

        selected_parts = [
            ranked[ranked["size_bucket"].eq(bucket)].head(PER_BUCKET)
            for bucket in range(BUCKET_COUNT)
        ]
        selected = pd.concat(selected_parts, ignore_index=False)
        if all(len(part) >= PER_BUCKET for part in selected_parts):
            complete_bucket_months += 1
        if len(selected) < TOP_N:
            missing = TOP_N - len(selected)
            fill = ranked[
                ~ranked["symbol"].astype(str).isin(
                    selected["symbol"].astype(str)
                )
            ].head(missing)
            selected = pd.concat([selected, fill], ignore_index=False)
        selected = selected.sort_values(
            ["factor_score", "symbol"],
            ascending=[False, True],
            kind="stable",
        ).head(TOP_N).copy()
        selected["rank"] = range(1, len(selected) + 1)
        selected["strategy_id"] = EXPERIMENT_ID
        neutral[str(signal_date)] = selected["symbol"].astype(str).tolist()
        holdings.extend([plain, selected])
    diagnostics = {
        "market_cap_coverage": covered_rows / max(len(enriched), 1),
        "complete_bucket_month_share": complete_bucket_months / max(total_months, 1),
        "candidate_median_market_cap_percentile": float(
            pd.concat(
                [
                    frame[frame["strategy_id"].eq(EXPERIMENT_ID)]
                    for frame in holdings
                    if "strategy_id" in frame
                ],
                ignore_index=True,
            )["market_cap_percentile"].median()
        )
        if holdings
        else 0.0,
    }
    return (
        {BASELINE_ID: baseline, EXPERIMENT_ID: neutral},
        pd.concat(holdings, ignore_index=True),
        diagnostics,
    )


def _style_residual(
    runs: dict[str, Any],
    hs300: pd.Series,
    csi500: pd.Series,
) -> dict[str, dict[str, Any]]:
    """复用冻结的两阶段走步残差门槛，Beta不读取锁定期。"""
    hs300_annual = _calendar_returns(hs300)
    style = _calendar_returns(csi500).subtract(hs300_annual, fill_value=0.0)
    output: dict[str, dict[str, Any]] = {}
    for strategy_id, run in runs.items():
        excess = _calendar_returns(run.result.daily_values).subtract(
            hs300_annual,
            fill_value=0.0,
        )
        output[strategy_id] = evaluate_single_candidate(
            strategy_id,
            excess,
            style,
        )
    return output


def evaluate_gate(
    *,
    candidate: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    stress: dict[str, float],
    candidate_residual: dict[str, Any],
    baseline_residual: dict[str, Any],
    size_diagnostics: dict[str, float],
) -> dict[str, Any]:
    """候选必须真实降低风格Beta且保留可交易的绝对收益。"""
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
        "annual_turnover_not_over_baseline_115pct": (
            full["annual_turnover"] <= baseline_full["annual_turnover"] * 1.15
        ),
        "stress_20bps_annual_return_at_least_7pct": (
            stress["annualized_return"] >= 0.07
        ),
        "market_cap_coverage_at_least_95pct": (
            size_diagnostics["market_cap_coverage"] >= 0.95
        ),
        "all_months_have_four_complete_buckets": (
            size_diagnostics["complete_bucket_month_share"] >= 1.0
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
            "市值分层组合通过走步残差与交易门槛，仅进入冻结前瞻确认"
            if passed
            else "市值分层组合未通过全部门槛，不修改现有策略或生产调度"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "市值分层研究报告"),
            ExperimentArtifact("holdings", holdings_path, "最新市值分层持仓"),
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
    diagnostics = result["size_diagnostics"]
    stress = result["stress_20bps_metrics"]
    return f"""# Quality Balanced Value 市值分层中性 V1

- 数据截止：{result['latest_date']}。
- Alpha、标准股票池、月频信号、日频风险层和M0均保持不变。
- 四个市值分位各选5只，市值只使用信号日已披露总股本。
- 本研究不修改生产策略或调度。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 走步中盘风格残差

| 策略 | 验证Beta | 锁定Beta | 验证残差 | 锁定残差 | 锁定正残差年 | 锁定IR | 最差锁定年 | 门槛 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
{residual_rows}

- 候选相对基线锁定Beta降幅：
  {result['gate']['locked_style_beta_reduction']:.2%}。

## 数据与组合诊断

- 市值覆盖：{diagnostics['market_cap_coverage']:.2%}。
- 四分位均可完整选满月份：{diagnostics['complete_bucket_month_share']:.2%}。
- 候选持仓市值分位中位数：
  {diagnostics['candidate_median_market_cap_percentile']:.2%}。
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
