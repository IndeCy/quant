"""净经营资产异常因子的点时数据可行性与独立性审计。"""

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
from data.net_operating_assets import (
    NET_OPERATING_ASSETS_TABLE,
    NetOperatingAssetsPaths,
    attach_net_operating_assets_database,
    create_net_operating_assets_signal_dates,
    materialize_net_operating_assets_asof,
)
from factors.net_operating_assets import score_net_operating_assets
from examples.net_operating_assets_feasibility_report import render_report
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "net_operating_assets_data_feasibility_v1"
REPORT_PATH = Path("docs/research/net-operating-assets-data-feasibility-v1.md")
STUDY_START = "20150101"
TOP_N = 40
MIN_CANDIDATES = 500
MIN_UNIQUE_VALUES = 450
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_STYLE_CORRELATION = 0.80
MAX_TRADING_ASSET_MISSING_SHARE = 0.90
MAX_ALL_DEBT_MISSING_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="净经营资产数据可行性 V1",
    category="data_feasibility",
    hypothesis="低净经营资产强度能否形成广泛、独立且可交易的A股候选池",
    definition={
        "factor": {
            "formula": (
                "[(total_assets-money_cap-trad_asset)-"
                "(total_liab-st_borr-lt_borr-bond_payable-"
                "st_bonds_payable-non_cur_liab_due_1y-lease_liab)]"
                "/total_assets"
            ),
            "direction": "lower_is_better",
            "optional_missing_components": "zero_with_missingness_audit",
            "transform": "raw_cross_sectional_percentile_rank",
        },
        "visibility": {
            "annual_1231_only": True,
            "f_ann_date_lte_signal_date": True,
            "latest_visible_revision": True,
            "report_types": ["1", "4"],
            "report_freshness_years": [1, 2],
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
            "trading_asset_missing_share_max": (
                MAX_TRADING_ASSET_MISSING_SHARE
            ),
            "all_debt_components_missing_share_max": (
                MAX_ALL_DEBT_MISSING_SHARE
            ),
            "duplicate_visibility_formula_violations": 0,
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
    """先登记确定性指纹，再扫描行情和资产负债表。"""
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
    """构造点时月末截面并执行冻结的数据门禁。"""
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
        create_net_operating_assets_signal_dates(connection, signal_dates)
        attach_net_operating_assets_database(
            connection,
            NetOperatingAssetsPaths(paths.balance_sheet_path),
        )
        materialize_net_operating_assets_asof(connection)
        source = load_investable_source(connection)
        diagnostics = load_diagnostics(connection, source)
    finally:
        connection.close()

    candidates = score_monthly_candidates(source)
    monthly = build_monthly_coverage(candidates, signal_dates)
    result = evaluate_feasibility(candidates, monthly, diagnostics, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_source(connection: Any) -> pd.DataFrame:
    """按统一股票池规则读取可投资 NOA 月末截面。"""
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
            WHERE f.trade_date IN (SELECT signal_date FROM noa_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            f.ret120,
            f.vol60,
            f.amount20 * 1000.0 AS adv_rmb,
            n.* EXCLUDE(signal_date, symbol)
        FROM features f
        JOIN {NET_OPERATING_ASSETS_TABLE} n
          ON f.trade_date = n.signal_date AND f.symbol = n.symbol
        JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date = na.signal_date
         AND f.symbol = na.symbol
         AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM noa_signal_dates)
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
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def score_monthly_candidates(source: pd.DataFrame) -> pd.DataFrame:
    """按月独立排名，避免跨期分布变化污染截面分数。"""
    frames: list[pd.DataFrame] = []
    for signal_date, group in source.groupby("signal_date", sort=True):
        scored = score_net_operating_assets(group)
        scored["signal_date"] = str(signal_date)
        frames.append(scored)
    if not frames:
        return source.iloc[0:0].assign(factor_score=pd.Series(dtype=float))
    return pd.concat(frames, ignore_index=True)


def load_diagnostics(
    connection: Any,
    source: pd.DataFrame,
) -> dict[str, float]:
    """审计公告边界、公式恒等式、重复和可选字段缺失。"""
    visibility, duplicates, formula_errors = connection.execute(
        f"""
        SELECT
            SUM(CASE WHEN publish_date > signal_date THEN 1 ELSE 0 END),
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol),
            SUM(
                CASE WHEN ABS(
                    net_operating_assets
                    - (operating_assets - operating_liabilities)
                ) > 0.000001 THEN 1 ELSE 0 END
            )
        FROM {NET_OPERATING_ASSETS_TABLE}
        """
    ).fetchone()
    return {
        "visibility_violations": float(visibility or 0),
        "duplicate_signal_symbol_rows": float(duplicates or 0),
        "formula_identity_violations": float(formula_errors or 0),
        "money_cap_missing_share": _mean_bool(source, "money_cap_missing"),
        "trading_asset_missing_share": _mean_bool(
            source,
            "trad_asset_missing",
        ),
        "all_debt_components_missing_share": _mean_bool(
            source,
            "all_debt_components_missing",
        ),
    }


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月并记录广度、可交易性和风格相关性。"""
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
                "unique_factor_values": int(group["noa_ratio"].nunique()),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": (
                    float(adv.median()) if len(adv) else 0.0
                ),
                "top40_tradable_share": (
                    float(adv.ge(5_000_000).mean()) if len(adv) else 0.0
                ),
                "spearman_ret120": _spearman(
                    group,
                    "factor_score",
                    "ret120",
                ),
                "spearman_vol60": _spearman(
                    group,
                    "factor_score",
                    "vol60",
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
    """应用查看未来收益前冻结的覆盖和独立性门槛。"""
    if monthly.empty:
        raise ValueError("净经营资产没有月末截面")
    values = pd.to_numeric(candidates["noa_ratio"], errors="coerce")
    invalid_rows = int((~np.isfinite(values)).sum())
    duplicate_rows = int(
        candidates.duplicated(["signal_date", "symbol"]).sum()
    )
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    correlations = {
        "ret120": float(monthly["spearman_ret120"].median()),
        "vol60": float(monthly["spearman_vol60"].median()),
        "log_adv": float(monthly["spearman_log_adv"].median()),
    }
    checks = {
        "qualified_month_share": (
            float(qualified.mean()) >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_momentum": (
            abs(correlations["ret120"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_low_volatility": (
            abs(correlations["vol60"]) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_liquidity_level": (
            abs(correlations["log_adv"]) <= MAX_STYLE_CORRELATION
        ),
        "trading_asset_missing_within_limit": (
            diagnostics["trading_asset_missing_share"]
            <= MAX_TRADING_ASSET_MISSING_SHARE
        ),
        "debt_components_missing_within_limit": (
            diagnostics["all_debt_components_missing_share"]
            <= MAX_ALL_DEBT_MISSING_SHARE
        ),
        "zero_visibility_violations": (
            diagnostics["visibility_violations"] == 0
        ),
        "zero_formula_identity_violations": (
            diagnostics["formula_identity_violations"] == 0
        ),
        "zero_duplicate_rows": (
            duplicate_rows == 0
            and diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
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
        "diagnostics": diagnostics,
        "duplicate_rows": duplicate_rows,
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
    """归档门禁和逐月覆盖，失败尝试同样保存。"""
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
            "净经营资产覆盖、独立性和可交易性通过，可执行一次固定回测"
            if result["passed"]
            else "净经营资产数据门禁未通过，终止于收益回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "逐月覆盖明细"),
        ],
    )


def _mean_bool(frame: pd.DataFrame, column: str) -> float:
    if frame.empty:
        return 1.0
    return float(frame[column].fillna(True).astype(bool).mean())


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    values = frame[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(values) <= 2:
        return float("nan")
    return float(values[left].corr(values[right], method="spearman"))


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
    values = pd.to_numeric(latest["noa_ratio"], errors="coerce")
    return {
        "p01": float(values.quantile(0.01)),
        "median": float(values.median()),
        "p99": float(values.quantile(0.99)),
    }


def _data_version(paths: RuntimePaths) -> str:
    """绑定资产负债表、行情和增量文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("balance", paths.balance_sheet_path),
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
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
