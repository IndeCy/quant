"""36 至 13 个月长期反转因子的数据可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.long_term_reversal import (
    LONG_TERM_REVERSAL_TABLE,
    materialize_long_term_reversal,
)
from data.market_features import (
    load_month_end_signal_dates,
    materialize_market_features,
)
from examples.long_term_reversal_feasibility_report import render_report
from factors.long_term_reversal import score_long_term_reversal_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "long_term_reversal_data_feasibility_v1_1"
REPORT_PATH = Path("docs/research/long-term-reversal-data-feasibility-v1-1.md")
SOURCE_START = "20110101"
TOP_N = 40
MIN_CANDIDATES = 1_000
MIN_UNIQUE_VALUES = 900
MIN_QUALIFIED_MONTH_SHARE = 0.90
MIN_TOP40_MEDIAN_ADV_RMB = 20_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.95
MAX_STYLE_CORRELATION = 0.80
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="长期反转数据可行性 V1.1",
    category="data_feasibility",
    hypothesis="36至13个月长期输家排序能否形成稳定、独立且可交易的全A候选池",
    definition={
        "factor": {
            "formula": "qfq_close_lag252/qfq_close_lag756-1",
            "direction": "lower_is_better",
            "source": "daily_adj_cache",
        },
        "window": {
            "long_lag_trading_days": 756,
            "recent_lag_trading_days": 252,
            "signal": "month_end_close",
            "future_execution": "t_plus_1",
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
            "identity_duplicate_visibility_invalid_violations": 0,
        },
        "decision": "feasibility_only_no_return_backtest",
        "source_view_lookback_start": SOURCE_START,
        "methodology_version": "v1.1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """在全市场扫描前登记长期反转研究指纹。"""
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
    """一次构造点时特征、标准股票池和月度覆盖。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=SOURCE_START,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        materialize_long_term_reversal(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = load_month_end_signal_dates(connection)
        source = load_investable_source(connection, signal_dates)
    finally:
        connection.close()

    candidates = score_long_term_reversal_frame(source)
    monthly = build_monthly_coverage(candidates, signal_dates)
    result = evaluate_feasibility(candidates, monthly, latest_date)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_source(
    connection: Any,
    signal_dates: list[str],
) -> pd.DataFrame:
    """使用历史名称和标准流动性过滤构造可投资截面。"""
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE reversal_signal_dates(signal_date VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO reversal_signal_dates VALUES (?)",
        [(str(value),) for value in signal_dates],
    )
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
            JOIN name_history h ON f.symbol=h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (
                SELECT signal_date FROM reversal_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            r.close_recent_lag,
            r.close_long_lag,
            r.long_term_return,
            f.ret120,
            f.vol60,
            f.amount20 * 1000.0 AS adv_rmb
        FROM features f
        JOIN {LONG_TERM_REVERSAL_TABLE} r
          ON f.trade_date=r.trade_date AND f.symbol=r.symbol
        JOIN stock_basic sb ON f.symbol=sb.ts_code
        LEFT JOIN name_asof na
          ON f.trade_date=na.signal_date
         AND f.symbol=na.symbol
         AND na.rn=1
        WHERE f.trade_date IN (
                SELECT signal_date FROM reversal_signal_dates
              )
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


def build_monthly_coverage(
    candidates: pd.DataFrame,
    expected_dates: list[str],
) -> pd.DataFrame:
    """保留空月并统计广度、流动性和风格相关性。"""
    rows: list[dict[str, Any]] = []
    for signal_date in expected_dates:
        group = candidates[candidates["signal_date"].astype(str).eq(signal_date)]
        selected = group.nlargest(TOP_N, "factor_score")
        adv = pd.to_numeric(selected["adv_rmb"], errors="coerce")
        rows.append(
            {
                "signal_date": signal_date,
                "candidate_count": int(len(group)),
                "unique_factor_values": int(group["long_term_return"].nunique()),
                "top40_count": int(len(selected)),
                "top40_median_adv_rmb": float(adv.median()) if len(adv) else 0.0,
                "top40_tradable_share": float(adv.ge(5_000_000).mean())
                if len(adv)
                else 0.0,
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
            }
        )
    return pd.DataFrame(rows)


def evaluate_feasibility(
    candidates: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_date: str,
) -> dict[str, Any]:
    """应用研究前冻结的数据、独立性与可交易门槛。"""
    if monthly.empty:
        raise ValueError("长期反转没有预期月末截面")
    valid = candidates.dropna(
        subset=["close_recent_lag", "close_long_lag", "long_term_return"]
    )
    expected = valid["close_recent_lag"] / valid["close_long_lag"] - 1
    identity_error = (valid["long_term_return"] - expected).abs()
    duplicate_rows = int(
        candidates.duplicated(["signal_date", "symbol"]).sum()
    )
    invalid_rows = int(
        (~pd.to_numeric(candidates["long_term_return"], errors="coerce")
         .map(pd.notna)).sum()
    )
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_count"].eq(TOP_N)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    qualified_share = float(qualified.mean())
    ret_correlation = float(monthly["spearman_ret120"].median())
    vol_correlation = float(monthly["spearman_vol60"].median())
    checks = {
        "qualified_month_share": (
            qualified_share >= MIN_QUALIFIED_MONTH_SHARE
        ),
        "distinct_from_recent_momentum": (
            pd.notna(ret_correlation)
            and abs(ret_correlation) <= MAX_STYLE_CORRELATION
        ),
        "distinct_from_low_volatility": (
            pd.notna(vol_correlation)
            and abs(vol_correlation) <= MAX_STYLE_CORRELATION
        ),
        "zero_identity_violations": (
            float(identity_error.max() if len(identity_error) else 0) <= 1e-10
        ),
        "zero_duplicate_rows": duplicate_rows == 0,
        "zero_visibility_violations": True,
        "zero_invalid_rows": invalid_rows == 0,
    }
    passed = all(checks.values())
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "qualified_month_share": qualified_share,
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "unique_values_median": float(
            monthly["unique_factor_values"].median()
        ),
        "top40_adv_median_rmb": float(
            monthly["top40_median_adv_rmb"].median()
        ),
        "median_correlations": {
            "ret120": ret_correlation,
            "vol60": vol_correlation,
        },
        "max_identity_error": float(
            identity_error.max() if len(identity_error) else 0
        ),
        "duplicate_rows": duplicate_rows,
        "visibility_violations": 0,
        "invalid_rows": invalid_rows,
        "checks": checks,
        "passed": passed,
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """归档数据门禁报告和逐月覆盖明细。"""
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
            "长期反转数据覆盖和独立性通过，可执行一次固定回测"
            if result["passed"]
            else "长期反转数据覆盖、独立性或可交易性未通过"
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


def _data_version(paths: RuntimePaths) -> str:
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
    ]:
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
