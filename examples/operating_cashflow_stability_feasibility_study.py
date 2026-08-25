"""五年经营现金流稳定性因子的数据可行性与独立性审计。"""

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
from data.operating_cashflow_stability import (
    OPERATING_CASHFLOW_STABILITY_TABLE,
    OperatingCashflowStabilityPaths,
    attach_operating_cashflow_databases,
    create_operating_cashflow_signal_dates,
    materialize_operating_cashflow_stability_asof,
)
from data.profitability_history import (
    PROFITABILITY_FLOOR_ASOF_TABLE,
    ProfitabilityHistoryPaths,
    attach_profitability_history_databases,
    create_profitability_signal_date_table,
    materialize_profitability_floor_asof,
)
from examples.operating_cashflow_stability_feasibility_report import (
    render_report,
)
from factors.operating_cashflow_stability import (
    score_operating_cashflow_stability,
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


EXPERIMENT_ID = "operating_cashflow_stability_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/operating-cashflow-stability-data-feasibility-v1.md"
)
STUDY_START = "20150101"
TOP_N = 40
MIN_CANDIDATES = 600
MIN_UNIQUE_VALUES = 550
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_STYLE_CORRELATION = 0.80
MAX_ZERO_STD_SHARE = 0.05
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="经营现金流稳定性数据可行性 V1",
    category="data_feasibility",
    hypothesis="低五年经营现金流波动能否形成广泛、独立且可交易的候选池",
    definition={
        "factor": {
            "formula": (
                "stddev_samp(annual_n_cashflow_act/"
                "average_current_prior_total_assets,last_5_consecutive_years)"
            ),
            "direction": "lower_is_better",
            "eligibility": "median_ocf_to_assets_5y_positive",
            "median_role": "stable_cash_burn_exclusion_only",
        },
        "visibility": {
            "annual_1231_only": True,
            "each_statement_latest_revision_f_ann_date_lte_signal": True,
            "synchronized_cashflow_and_balance": True,
            "latest_fiscal_year_age": [1, 2],
            "consecutive_fiscal_years_required": True,
        },
        "company_type": "1_general_industry",
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "candidate_portfolio": {"top_n": TOP_N, "weight": "equal"},
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_QUALIFIED_MONTH_SHARE,
            "top40_median_adv_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "top40_tradable_share": MIN_TOP40_TRADABLE_SHARE,
            "maximum_style_rank_correlation": MAX_STYLE_CORRELATION,
            "maximum_zero_std_share": MAX_ZERO_STD_SHARE,
            "duplicate_visibility_window_violations": 0,
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
    """先登记研究指纹，再扫描行情和财务历史。"""
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
    """物化连续五年现金流窗口并执行冻结门禁。"""
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
        create_operating_cashflow_signal_dates(connection, signal_dates)
        attach_operating_cashflow_databases(
            connection,
            OperatingCashflowStabilityPaths(
                paths.cashflow_statement_path,
                paths.balance_sheet_path,
            ),
        )
        materialize_operating_cashflow_stability_asof(connection)
        # 临时表已完成物化，释放同源文件后再挂载 ROA 稳定性对照。
        connection.execute("DETACH ocf_cashflow_db")
        connection.execute("DETACH ocf_balance_db")
        create_profitability_signal_date_table(connection, signal_dates)
        attach_profitability_history_databases(
            connection,
            ProfitabilityHistoryPaths(
                paths.fina_indicator_path,
                paths.income_statement_path,
                paths.balance_sheet_path,
                paths.cashflow_statement_path,
            ),
        )
        materialize_profitability_floor_asof(connection)
        source = load_investable_source(connection)
    finally:
        connection.close()

    candidates = score_monthly_candidates(source)
    monthly = build_monthly_coverage(candidates, signal_dates)
    result = evaluate_feasibility(candidates, monthly, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_source(connection: Any) -> pd.DataFrame:
    """连接标准股票池、OCF 稳定性和 ROA 稳定性对照。"""
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
            WHERE f.trade_date IN (
                SELECT signal_date FROM ocf_stability_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            o.* EXCLUDE(signal_date, symbol),
            p.roa_std_5y,
            f.ret120,
            f.vol60,
            f.amount20 * 1000.0 AS adv_rmb
        FROM features f
        JOIN {OPERATING_CASHFLOW_STABILITY_TABLE} o
          ON f.trade_date = o.signal_date AND f.symbol = o.symbol
        LEFT JOIN {PROFITABILITY_FLOOR_ASOF_TABLE} p
          ON f.trade_date = p.signal_date AND f.symbol = p.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.st_name IS NULL
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


def score_monthly_candidates(source: pd.DataFrame) -> pd.DataFrame:
    """每个月独立过滤稳定现金流并计算截面秩。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        scored = score_operating_cashflow_stability(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    if not frames:
        return source.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
    return pd.concat(frames, ignore_index=True)


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月并统计覆盖、流动性和风格相关性。"""
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
                    group["ocf_assets_std_5y"].nunique()
                ),
                "zero_std_share": float(
                    group["ocf_assets_std_5y"].eq(0).mean()
                    if len(group)
                    else 1.0
                ),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": (
                    float(adv.median()) if len(adv) else 0.0
                ),
                "top40_tradable_share": (
                    float(adv.ge(5_000_000).mean()) if len(adv) else 0.0
                ),
                "spearman_roa_stability": _spearman_low(
                    group,
                    "factor_score",
                    "roa_std_5y",
                ),
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
    latest_date: str,
) -> dict[str, Any]:
    """执行查看未来收益前冻结的数据与排重门槛。"""
    if monthly.empty:
        raise ValueError("经营现金流稳定性没有月末截面")
    duplicate_rows = int(
        candidates.duplicated(["signal_date", "symbol"]).sum()
    )
    visibility = int(
        (
            candidates["latest_publish_date"].astype(str)
            > candidates["signal_date"].astype(str)
        ).sum()
    )
    window_violations = int(candidates["observations"].ne(5).sum())
    invalid_rows = int(
        (
            ~np.isfinite(
                pd.to_numeric(
                    candidates["ocf_assets_std_5y"],
                    errors="coerce",
                )
            )
        ).sum()
    )
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["zero_std_share"].le(MAX_ZERO_STD_SHARE)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    correlations = {
        "roa_stability": float(
            monthly["spearman_roa_stability"].median()
        ),
        "vol60": float(monthly["spearman_vol60"].median()),
        "ret120": float(monthly["spearman_ret120"].median()),
        "log_adv": float(monthly["spearman_log_adv"].median()),
    }
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_roa_stability": (
            abs(correlations["roa_stability"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_price_low_volatility": (
            abs(correlations["vol60"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_momentum": (
            abs(correlations["ret120"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_liquidity_level": (
            abs(correlations["log_adv"]) <= MAX_STYLE_CORRELATION
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_visibility_violations": visibility == 0,
        "zero_window_violations": window_violations == 0,
        "zero_invalid_rows": invalid_rows == 0,
    }
    passed = all(checks.values())
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
        "latest_distribution": _latest_distribution(candidates),
        "duplicate_rows": duplicate_rows,
        "visibility_violations": visibility,
        "window_violations": window_violations,
        "invalid_rows": invalid_rows,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档门禁与逐月覆盖，失败尝试同样保留。"""
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
            "现金流稳定性覆盖和独立性通过，可执行一次固定回测"
            if result["passed"]
            else "现金流稳定性数据、排重或可交易性门禁未通过"
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


def _latest_distribution(candidates: pd.DataFrame) -> dict[str, float]:
    latest = candidates[
        candidates["signal_date"].eq(candidates["signal_date"].max())
    ]
    values = pd.to_numeric(latest["ocf_assets_std_5y"], errors="coerce")
    return {
        "std_p01": float(values.quantile(0.01)),
        "std_median": float(values.median()),
        "std_p99": float(values.quantile(0.99)),
        "ocf_median": float(latest["ocf_assets_median_5y"].median()),
    }


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情、四张财务库和增量版本。"""
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
