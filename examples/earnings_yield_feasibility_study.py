"""正盈利公司的点时盈利收益率数据可行性与独立性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from data.quality_financial import (
    QualityFinancialPaths,
    attach_quality_financial_databases,
    create_quality_signal_date_table,
    materialize_quality_financial_asof,
)
from data.quality_value_lowvol import (
    MATERIAL_ADJ_FACTOR_CHANGE,
    attach_report_adjustment_factors,
)
from examples.earnings_yield_feasibility_report import render_report
from factors.earnings_yield import score_earnings_yield
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)
from strategies.quality_universe import load_annual_quality_candidates


EXPERIMENT_ID = "earnings_yield_data_feasibility_v1"
REPORT_PATH = Path("docs/research/earnings-yield-data-feasibility-v1.md")
STUDY_START = "20150101"
TOP_N = 40
MIN_CANDIDATES = 800
MIN_UNIQUE_VALUES = 750
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_STYLE_CORRELATION = 0.80
MAX_ADJUSTMENT_MISSING_SHARE = 0.01
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="点时盈利收益率数据可行性 V1",
    category="data_feasibility",
    hypothesis="高年报EPS相对当前价格能否形成广泛、独立且可交易的价值截面",
    definition={
        "factor": {
            "formula": "latest_visible_annual_eps/raw_close_on_signal_date",
            "direction": "higher_is_better",
            "eligibility": "eps_positive",
            "price_policy": "raw_close_for_valuation_qfq_reserved_for_execution",
        },
        "visibility": {
            "annual_1231_only": True,
            "publish_date": "max_income_balance_cashflow_f_ann_date",
            "publish_date_lte_signal_date": True,
            "report_freshness_years": [1, 2],
        },
        "corporate_action_gate": {
            "report_to_signal_adj_factor_change_max": (
                MATERIAL_ADJ_FACTOR_CHANGE
            ),
            "missing_adjustment_rejected": True,
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "candidate_portfolio": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "maximum_style_rank_correlation": MAX_STYLE_CORRELATION,
            "adjustment_missing_share_max": MAX_ADJUSTMENT_MISSING_SHARE,
            "duplicate_visibility_invalid_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记确定性指纹，再扫描财务与行情截面。"""
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
    """构造点时估值截面并执行冻结门禁。"""
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
        attach_quality_financial_databases(
            connection,
            _financial_paths(paths),
        )
        materialize_quality_financial_asof(connection, annual_only=True)
        source = load_annual_quality_candidates(connection)
        source = attach_report_adjustment_factors(connection, source)
    finally:
        connection.close()

    candidates, diagnostics = build_candidates(source)
    scored = score_monthly_candidates(candidates)
    monthly = build_monthly_coverage(scored, signal_dates)
    result = evaluate_feasibility(scored, monthly, diagnostics, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def build_candidates(source: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """应用标准股票池、年报新鲜度与公司行为门禁。"""
    data = source.copy()
    signal = pd.to_datetime(data["signal_date"], format="%Y%m%d")
    listed = pd.to_datetime(data["list_date"], format="%Y%m%d", errors="coerce")
    delisted = pd.to_datetime(
        data["delist_date"],
        format="%Y%m%d",
        errors="coerce",
    )
    report_year = pd.to_numeric(
        data["end_date"].astype(str).str[:4],
        errors="coerce",
    )
    signal_year = signal.dt.year
    numeric = [
        "eps",
        "raw_close",
        "current_adj_factor",
        "report_adj_factor",
        "roa",
        "vol60",
        "ret120",
        "amount20",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    adjustment_available = data[
        ["current_adj_factor", "report_adj_factor"]
    ].notna().all(axis=1)
    adjustment_change = (
        data["current_adj_factor"] / data["report_adj_factor"] - 1.0
    ).abs()
    material_action = (
        adjustment_available
        & adjustment_change.gt(MATERIAL_ADJ_FACTOR_CHANGE)
    )
    listed_three_years = (signal - listed).dt.days.ge(1095)
    delisted_asof = delisted.notna() & delisted.le(signal)
    valid = (
        listed_three_years
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~delisted_asof
        & data["end_date"].astype(str).str.endswith("1231")
        & data["f_ann_date"].astype(str).le(data["signal_date"].astype(str))
        & (signal_year - report_year).between(1, 2)
        & data["eps"].gt(0)
        & data["raw_close"].gt(0)
        & adjustment_available
        & ~material_action
    )
    accepted = data[valid].copy()
    accepted["earnings_yield"] = (
        accepted["eps"] / accepted["raw_close"]
    )
    accepted["adv_rmb"] = accepted["amount20"] * 1000.0
    duplicates = int(
        accepted.duplicated(["signal_date", "symbol"]).sum()
    )
    invalid = int(
        (
            ~np.isfinite(
                pd.to_numeric(accepted["earnings_yield"], errors="coerce")
            )
        ).sum()
    )
    diagnostics = {
        "adjustment_missing_share": float((~adjustment_available).mean()),
        "material_action_share": float(material_action.mean()),
        "visibility_violations": float(
            (
                accepted["f_ann_date"].astype(str)
                > accepted["signal_date"].astype(str)
            ).sum()
        ),
        "duplicate_rows": float(duplicates),
        "invalid_rows": float(invalid),
    }
    return accepted, diagnostics


def score_monthly_candidates(source: pd.DataFrame) -> pd.DataFrame:
    """按月独立计算 E/P 截面秩。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        scored = score_earnings_yield(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    if not frames:
        return source.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
    return pd.concat(frames, ignore_index=True)


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月并记录广度、流动性和风格相关性。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[
            candidates["signal_date"].astype(str).eq(signal_date)
        ]
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(len(group)),
                "unique_factor_values": int(
                    group["earnings_yield"].nunique()
                ),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": (
                    float(adv.median()) if len(adv) else 0.0
                ),
                "top40_tradable_share": (
                    float(adv.ge(5_000_000).mean()) if len(adv) else 0.0
                ),
                "spearman_roa": _spearman(group, "factor_score", "roa"),
                "spearman_vol60": _spearman_low(
                    group,
                    "factor_score",
                    "vol60",
                ),
                "spearman_ret120": _spearman(
                    group,
                    "factor_score",
                    "ret120",
                ),
                "spearman_log_adv": _spearman_log_adv(group),
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行查看未来收益前冻结的覆盖与排重门槛。"""
    if monthly.empty:
        raise ValueError("盈利收益率没有月末截面")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    correlations = {
        "roa": float(monthly["spearman_roa"].median()),
        "vol60": float(monthly["spearman_vol60"].median()),
        "ret120": float(monthly["spearman_ret120"].median()),
        "log_adv": float(monthly["spearman_log_adv"].median()),
    }
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_roa": abs(correlations["roa"]) <= MAX_STYLE_CORRELATION,
        "distinct_from_price_low_volatility": (
            abs(correlations["vol60"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_momentum": (
            abs(correlations["ret120"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_liquidity_level": (
            abs(correlations["log_adv"]) <= MAX_STYLE_CORRELATION
        ),
        "adjustment_missing_within_limit": (
            diagnostics["adjustment_missing_share"]
            <= MAX_ADJUSTMENT_MISSING_SHARE
        ),
        "zero_visibility_violations": (
            diagnostics["visibility_violations"] == 0
        ),
        "zero_duplicate_rows": diagnostics["duplicate_rows"] == 0,
        "zero_invalid_rows": diagnostics["invalid_rows"] == 0,
    }
    passed = all(checks.values())
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]["earnings_yield"]
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "qualified_month_share": float(qualified.mean()),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "unique_values_median": float(
            monthly["unique_factor_values"].median()
        ),
        "top40_adv_median_rmb": float(
            monthly["top40_median_adv_rmb"].median()
        ),
        "median_correlations": correlations,
        "latest_distribution": {
            "p01": float(latest.quantile(0.01)),
            "median": float(latest.median()),
            "p99": float(latest.quantile(0.99)),
        },
        "diagnostics": diagnostics,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档门禁与逐月覆盖，失败尝试同样保存。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if result["passed"] else "REJECTED",
        decision_reason=(
            "盈利收益率覆盖和独立性通过，可执行一次固定回测"
            if result["passed"]
            else "盈利收益率数据、排重或公司行为门禁未通过"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖明细"),
        ],
    )


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(values[right], method="spearman"))


def _spearman_low(frame: pd.DataFrame, left: str, right: str) -> float:
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(-values[right], method="spearman"))


def _spearman_log_adv(frame: pd.DataFrame) -> float:
    values = frame[["factor_score", "adv_rmb"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    values = values[values["adv_rmb"].gt(0)].dropna()
    if len(values) <= 2:
        return float("nan")
    return float(
        values["factor_score"].corr(
            np.log(values["adv_rmb"]),
            method="spearman",
        )
    )


def _financial_paths(paths: RuntimePaths) -> QualityFinancialPaths:
    return QualityFinancialPaths(
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、财务和增量版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("indicator", paths.fina_indicator_path),
        ("income", paths.income_statement_path),
        ("balance", paths.balance_sheet_path),
        ("cashflow", paths.cashflow_statement_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


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
