"""低下行 Beta 因子的数据、排重与可交易性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.benchmark_series import load_adjusted_fund_curve
from data.downside_beta import (
    DOWNSIDE_BETA_TABLE,
    create_downside_beta_signal_dates,
    materialize_downside_beta,
)
from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from examples.downside_beta_feasibility_report import render_report
from factors.downside_beta import score_downside_beta_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "downside_beta_data_feasibility_v1"
REPORT_PATH = Path("docs/research/downside-beta-data-feasibility-v1.md")
STUDY_START = "20150101"
LOCKED_START = "20240101"
WINDOW = 252
MIN_OBSERVATIONS = 200
MIN_DOWN_OBSERVATIONS = 60
TOP_N = 40
MIN_CANDIDATES = 1000
MIN_UNIQUE_VALUES = 800
MIN_MONTH_SHARE = 0.90
MAX_TOTAL_BETA_CORRELATION = 0.85
MAX_LOW_VOL_CORRELATION = 0.80
MIN_TOP40_MEDIAN_ADV_RMB = 10_000_000.0
MIN_TOP40_ADV_RMB = 5_000_000.0
MIN_TOP40_TRADABLE_SHARE = 0.90
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="低下行Beta数据与排重可行性 V1",
    category="data_feasibility",
    hypothesis="只在沪深300下跌日估计的Beta能否形成区别于低Beta和低波的防御截面",
    definition={
        "factor": {
            "formula": (
                "cov(stock_return,510300_return|market_return<0)"
                "/var(510300_return|market_return<0)"
            ),
            "direction": "lower_is_better",
            "window": WINDOW,
            "min_observations": MIN_OBSERVATIONS,
            "min_down_observations": MIN_DOWN_OBSERVATIONS,
            "valid_downside_beta": [0.0, 3.0],
            "valid_total_beta": [0.0, 3.0],
        },
        "visibility": {
            "same_day_close_signal_next_trading_day_execution": True,
            "rolling_window_uses_current_and_past_only": True,
            "benchmark": "510300.SH_qfq",
        },
        "universe": "listed_3y_ex_st_delisted_suspended_bottom20_amount",
        "semantic_deduplication": {
            "maximum_median_spearman_with_low_total_beta": (
                MAX_TOTAL_BETA_CORRELATION
            ),
            "maximum_median_spearman_with_low_vol60": MAX_LOW_VOL_CORRELATION,
        },
        "tradability": {
            "reference_capital": 5_000_000,
            "top_n": TOP_N,
            "median_adv_floor_rmb": MIN_TOP40_MEDIAN_ADV_RMB,
            "single_name_adv_floor_rmb": MIN_TOP40_ADV_RMB,
            "minimum_name_share_above_floor": MIN_TOP40_TRADABLE_SHARE,
        },
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "unique_value_floor": MIN_UNIQUE_VALUES,
            "qualified_month_share": MIN_MONTH_SHARE,
            "locked_period_same_gate": True,
            "semantic_independence_required": True,
            "duplicate_signal_symbol_rows": 0,
            "observation_violations": 0,
        },
        "decision": "feasibility_only_no_backtest",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记研究指纹，再加载历史行情和基准。"""
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
    """物化下行 Beta，并在收益回测前执行语义排重。"""
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
        benchmark = load_adjusted_fund_curve(
            paths.fund_daily_history_path,
            paths.benchmark_increment_path,
            "510300.SH",
            end_date=latest_date,
        )
        create_downside_beta_signal_dates(connection, signal_dates)
        materialize_downside_beta(
            connection,
            benchmark,
            window=WINDOW,
            min_observations=MIN_OBSERVATIONS,
            min_down_observations=MIN_DOWN_OBSERVATIONS,
        )
        panel = load_investable_panel(connection)
        monthly = build_monthly_coverage(panel)
        distribution = build_latest_distribution(panel)
        diagnostics = load_diagnostics(connection, panel)
    finally:
        connection.close()
    result = evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        latest_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_investable_panel(connection: Any) -> pd.DataFrame:
    """连接标准股票池、下行 Beta 和价格风格诊断字段。"""
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
                SELECT signal_date FROM downside_beta_signal_dates
            )
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            d.observations,
            d.downside_observations,
            d.upside_observations,
            d.total_beta,
            d.downside_beta,
            d.upside_beta,
            f.amount20 * 1000.0 AS amount20_rmb,
            f.vol60,
            f.ret120
        FROM features f
        JOIN {DOWNSIDE_BETA_TABLE} d
          ON f.trade_date = d.signal_date AND f.symbol = d.symbol
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


def build_monthly_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """统计覆盖、辨识度和拟选 Top40 的成交能力。"""
    rows: list[dict[str, Any]] = []
    for signal_date, group in panel.groupby("signal_date", sort=True):
        scored = score_downside_beta_frame(group)
        top = scored.nlargest(TOP_N, "factor_score")
        rows.append(
            {
                "signal_date": str(signal_date),
                "candidate_count": int(len(scored)),
                "unique_factor_values": int(scored["downside_beta"].nunique()),
                "top40_median_adv_rmb": float(top["amount20_rmb"].median()),
                "top40_tradable_share": float(
                    top["amount20_rmb"].ge(MIN_TOP40_ADV_RMB).mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def build_latest_distribution(panel: pd.DataFrame) -> dict[str, float]:
    """记录最新下行、总和上行 Beta 的分布。"""
    latest = panel[panel["signal_date"].eq(panel["signal_date"].max())]
    latest = score_downside_beta_frame(latest)
    return {
        "downside_p01": float(latest["downside_beta"].quantile(0.01)),
        "downside_median": float(latest["downside_beta"].median()),
        "downside_p99": float(latest["downside_beta"].quantile(0.99)),
        "total_beta_median": float(latest["total_beta"].median()),
        "upside_beta_median": float(latest["upside_beta"].median()),
    }


def load_diagnostics(
    connection: Any,
    panel: pd.DataFrame,
) -> dict[str, float]:
    """检查窗口完整性，并量化与低总 Beta、低波的重合。"""
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) - COUNT(DISTINCT signal_date || ':' || symbol),
            SUM(
                CASE WHEN observations < {MIN_OBSERVATIONS}
                       OR downside_observations < {MIN_DOWN_OBSERVATIONS}
                     THEN 1 ELSE 0 END
            )
        FROM {DOWNSIDE_BETA_TABLE}
        """
    ).fetchone()
    correlations: dict[str, list[float]] = {
        "low_total_beta": [],
        "low_vol60": [],
        "amount20_rmb": [],
        "ret120": [],
    }
    overlaps: dict[str, list[float]] = {
        "low_total_beta": [],
        "low_vol60": [],
    }
    for _, group in panel.groupby("signal_date", sort=True):
        scored = score_downside_beta_frame(group)
        if len(scored) < TOP_N:
            continue
        rank = scored["factor_score"].rank()
        comparisons = {
            "low_total_beta": -scored["total_beta"],
            "low_vol60": -scored["vol60"],
            "amount20_rmb": scored["amount20_rmb"],
            "ret120": scored["ret120"],
        }
        for key, values in comparisons.items():
            value = rank.corr(values.rank())
            if pd.notna(value):
                correlations[key].append(float(value))
        selected = set(
            scored.nlargest(TOP_N, "factor_score")["symbol"].astype(str)
        )
        comparators = {
            "low_total_beta": scored.nsmallest(TOP_N, "total_beta"),
            "low_vol60": scored.nsmallest(TOP_N, "vol60"),
        }
        for key, comparator in comparators.items():
            overlaps[key].append(
                len(selected & set(comparator["symbol"].astype(str))) / TOP_N
            )
    return {
        "duplicate_signal_symbol_rows": float(row[0] or 0),
        "observation_violations": float(row[1] or 0),
        "median_spearman_with_low_total_beta": _median(
            correlations["low_total_beta"]
        ),
        "median_spearman_with_low_vol60": _median(
            correlations["low_vol60"]
        ),
        "median_spearman_with_amount20": _median(
            correlations["amount20_rmb"]
        ),
        "median_spearman_with_ret120": _median(correlations["ret120"]),
        "median_top40_overlap_with_low_total_beta": _median(
            overlaps["low_total_beta"]
        ),
        "median_top40_overlap_with_low_vol60": _median(
            overlaps["low_vol60"]
        ),
    }


def evaluate_feasibility(
    monthly: pd.DataFrame,
    distribution: dict[str, float],
    diagnostics: dict[str, float],
    latest_date: str,
) -> dict[str, Any]:
    """执行数据、语义排重和个人资金可交易性门槛。"""
    if monthly.empty:
        raise ValueError("下行Beta覆盖审计没有月末数据")
    qualified = (
        monthly["candidate_count"].ge(MIN_CANDIDATES)
        & monthly["unique_factor_values"].ge(MIN_UNIQUE_VALUES)
        & monthly["top40_median_adv_rmb"].ge(MIN_TOP40_MEDIAN_ADV_RMB)
        & monthly["top40_tradable_share"].ge(MIN_TOP40_TRADABLE_SHARE)
    )
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    locked_qualified = qualified.loc[locked.index]
    full_share = float(qualified.mean())
    locked_share = float(
        locked_qualified.mean() if not locked.empty else 0.0
    )
    checks = {
        "full_qualified_month_share": full_share >= MIN_MONTH_SHARE,
        "locked_qualified_month_share": locked_share >= MIN_MONTH_SHARE,
        "distinct_from_low_total_beta": abs(
            diagnostics["median_spearman_with_low_total_beta"]
        ) <= MAX_TOTAL_BETA_CORRELATION,
        "distinct_from_low_vol60": abs(
            diagnostics["median_spearman_with_low_vol60"]
        ) <= MAX_LOW_VOL_CORRELATION,
        "zero_duplicate_signal_symbol_rows": (
            diagnostics["duplicate_signal_symbol_rows"] == 0
        ),
        "zero_observation_violations": (
            diagnostics["observation_violations"] == 0
        ),
        "finite_latest_distribution": all(
            pd.notna(value) for value in distribution.values()
        ),
    }
    return {
        "latest_date": latest_date,
        "signal_months": int(len(monthly)),
        "candidate_count_min": int(monthly["candidate_count"].min()),
        "candidate_count_median": float(monthly["candidate_count"].median()),
        "candidate_count_latest": int(monthly["candidate_count"].iloc[-1]),
        "unique_value_min": int(monthly["unique_factor_values"].min()),
        "minimum_top40_median_adv_rmb": float(
            monthly["top40_median_adv_rmb"].min()
        ),
        "minimum_top40_tradable_share": float(
            monthly["top40_tradable_share"].min()
        ),
        "full_qualified_month_share": full_share,
        "locked_qualified_month_share": locked_share,
        "latest_distribution": distribution,
        "diagnostics": diagnostics,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档可行性结论和月度覆盖明细。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "低下行Beta数据、独立性和成交能力通过，可进入固定回测"
            if passed
            else "低下行Beta未通过冻结数据、排重或成交门槛，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "数据可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度覆盖明细"),
        ],
    )


def _median(values: list[float]) -> float:
    valid = [value for value in values if pd.notna(value)]
    return float(pd.Series(valid).median()) if valid else float("nan")


def _data_version(paths: RuntimePaths) -> str:
    """绑定行情与基准文件版本。"""
    parts: list[str] = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("live_increment", paths.live_market_increment_path),
        ("fund_history", paths.fund_daily_history_path),
        ("benchmark_increment", paths.benchmark_increment_path),
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
