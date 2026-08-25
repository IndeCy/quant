"""融资净买入强度因子的权限、历史覆盖与点时可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd
import tushare as ts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.margin_flow import (
    MARGIN_FLOW_ASOF_TABLE,
    create_margin_signal_date_table,
    materialize_margin_flow_asof,
)
from data.margin_trades import (
    MARGIN_SYNC_TABLE,
    attach_margin_trade_database,
    update_margin_trade_cache,
)
from data.market_features import load_month_end_signal_dates, materialize_market_features
from runtime.config import get_config_value
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "margin_flow_data_feasibility_v1"
REPORT_PATH = Path("docs/research/margin-flow-data-feasibility-v1.md")
FETCH_START = "20141201"
STUDY_START = "20150101"
LOCKED_START = "20220101"
LOOKBACK_TRADING_DAYS = 20
MIN_DAILY_ROWS = 300
MIN_DAILY_COVERAGE = 0.99
MIN_MONTHLY_VALID_MEDIAN = 500
MIN_POSITIVE_MEDIAN = 100
MIN_LOCKED_NONEMPTY_SHARE = 1.0

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="融资净买入强度数据可行性 V1",
    category="data_feasibility",
    hypothesis="融资净买入相对成交额能否形成时点可信、长期完整的月频资金行为因子",
    definition={
        "source": {
            "provider": "tushare",
            "endpoint": "margin_detail",
            "history_start": FETCH_START,
            "cache": "margin_trade_increment.duckdb",
        },
        "factor_preview": {
            "formula": "sum(rzmre-rzche,20d)/sum(turnover_amount,20d)",
            "lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "positive_only": True,
        },
        "visibility": {
            "provider_publish_time": "next_trade_day_0830",
            "signal_date_uses_data_through": "previous_trade_day",
            "execution": "signal_T_execute_T_plus_1",
        },
        "frozen_gates": {
            "daily_row_floor": MIN_DAILY_ROWS,
            "daily_coverage_share": MIN_DAILY_COVERAGE,
            "monthly_valid_median": MIN_MONTHLY_VALID_MEDIAN,
            "positive_candidate_median": MIN_POSITIVE_MEDIAN,
            "locked_nonempty_share": MIN_LOCKED_NONEMPTY_SHARE,
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
    """先登记研究身份，再执行可能耗时的历史下载。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=f"tushare_margin_detail:{FETCH_START}:{as_of_date}",
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
    """更新逐日缓存，并按 T-1 可见性统计月度候选覆盖。"""
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN")
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=FETCH_START,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(
            connection,
            lookback_start=FETCH_START,
            research_start=FETCH_START,
        )
        all_dates = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT DISTINCT trade_date
                FROM features
                WHERE trade_date >= ? AND trade_date < ?
                ORDER BY trade_date
                """,
                [FETCH_START, as_of_date],
            ).fetchall()
        ]
        update_result = update_margin_trade_cache(
            ts.pro_api(token),
            paths.margin_trade_path,
            all_dates,
            request_interval_seconds=0.02,
            progress_callback=_print_progress,
        )
        if not update_result.success:
            raise RuntimeError(
                f"融资融券缓存仍有失败交易日: {list(update_result.failed_dates)[:10]}"
            )
        attach_margin_trade_database(connection, paths.margin_trade_path)
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value < as_of_date
        ]
        create_margin_signal_date_table(connection, signal_dates)
        materialize_margin_flow_asof(
            connection,
            lookback_trading_days=LOOKBACK_TRADING_DAYS,
        )
        daily = load_daily_coverage(connection, FETCH_START, as_of_date)
        monthly = load_monthly_factor_coverage(connection)
        latest_date = str(max(all_dates))
    finally:
        connection.close()

    result = evaluate_feasibility(daily, monthly, latest_date)
    result["update"] = {
        "requested_dates": update_result.requested_dates,
        "skipped_dates": update_result.skipped_dates,
        "fetched_dates": update_result.fetched_dates,
        "fetched_rows": update_result.fetched_rows,
    }
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["daily_records"] = daily.to_dict("records")
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def load_daily_coverage(
    connection: Any,
    start_date: str,
    as_of_date: str,
) -> pd.DataFrame:
    """比较真实交易日与成功缓存日期，空日不能被静默忽略。"""
    return connection.execute(
        f"""
        WITH expected AS (
            SELECT DISTINCT trade_date
            FROM features
            WHERE trade_date >= ? AND trade_date < ?
        ),
        actual AS (
            SELECT trade_date, row_count, status
            FROM margin_db.{MARGIN_SYNC_TABLE}
        )
        SELECT
            e.trade_date,
            COALESCE(a.row_count, 0) AS row_count,
            COALESCE(a.status, 'MISSING') AS status
        FROM expected e
        LEFT JOIN actual a USING(trade_date)
        ORDER BY e.trade_date
        """,
        [start_date, as_of_date],
    ).fetchdf()


def load_monthly_factor_coverage(connection: Any) -> pd.DataFrame:
    """使用连续 20 个真实交易日、且截止 T-1 的融资流计算覆盖。"""
    return connection.execute(
        f"""
        SELECT
            signal_date,
            MAX(visible_through_date) AS visible_through_date,
            COUNT(*) AS valid_count,
            COUNT(*) FILTER(WHERE margin_flow_intensity > 0) AS positive_count
        FROM {MARGIN_FLOW_ASOF_TABLE}
        GROUP BY signal_date
        ORDER BY signal_date
        """
    ).fetchdf()


def evaluate_feasibility(
    daily: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_date: str,
) -> dict[str, Any]:
    """按冻结门槛判断是否值得进入收益回测。"""
    if daily.empty or monthly.empty:
        raise ValueError("融资融券覆盖审计缺少日频或月频结果")
    daily_ok = daily["status"].eq("SUCCESS") & daily["row_count"].ge(MIN_DAILY_ROWS)
    locked = monthly[monthly["signal_date"].astype(str).ge(LOCKED_START)]
    daily_coverage = float(daily_ok.mean())
    valid_median = float(monthly["valid_count"].median())
    positive_median = float(monthly["positive_count"].median())
    locked_nonempty = float(
        locked["positive_count"].gt(0).mean() if not locked.empty else 0.0
    )
    checks = {
        "daily_coverage": daily_coverage >= MIN_DAILY_COVERAGE,
        "monthly_valid_median": valid_median >= MIN_MONTHLY_VALID_MEDIAN,
        "positive_candidate_median": positive_median >= MIN_POSITIVE_MEDIAN,
        "locked_nonempty_share": locked_nonempty >= MIN_LOCKED_NONEMPTY_SHARE,
    }
    return {
        "latest_date": latest_date,
        "expected_trading_days": int(len(daily)),
        "daily_coverage": daily_coverage,
        "daily_min_rows": int(daily["row_count"].min()),
        "signal_months": int(len(monthly)),
        "monthly_valid_median": valid_median,
        "positive_candidate_median": positive_median,
        "locked_nonempty_share": locked_nonempty,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": (
            "CONTINUE_TO_FIXED_BACKTEST"
            if all(checks.values())
            else "REJECTED_BEFORE_BACKTEST"
        ),
    }


def _print_progress(index: int, total: int, trade_date: str) -> None:
    """长历史下载每 100 日输出一次可见进度。"""
    if index == 1 or index == total or index % 100 == 0:
        print(f"margin cache progress: {index}/{total} ({trade_date})", flush=True)


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    daily = pd.DataFrame(result.pop("daily_records"))
    monthly = pd.DataFrame(result.pop("monthly_records"))
    daily_path = attempt.output_dir / "daily_coverage.csv"
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    daily.to_csv(daily_path, index=False)
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "两融数据覆盖和 T-1 可见性通过，可进入固定回测"
            if passed
            else "两融数据覆盖不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "两融数据可行性报告"),
            ExperimentArtifact("daily_coverage", daily_path, "逐日缓存覆盖"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月频因子覆盖"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 融资净买入强度数据可行性 V1

- 数据截止：{result['latest_date']}，交易日：
  {result['expected_trading_days']}。
- 日频完整覆盖：{result['daily_coverage']:.2%}，单日最少：
  {result['daily_min_rows']} 只。
- 月度有效候选中位数：{result['monthly_valid_median']:.0f}。
- 正融资净买入候选中位数：{result['positive_candidate_median']:.0f}。
- 2022 年后非空月份：{result['locked_nonempty_share']:.2%}。
- 时点规则：T 日信号只使用 T-1 及以前已于次日 8:30 披露的数据。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未接入生产日更。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
