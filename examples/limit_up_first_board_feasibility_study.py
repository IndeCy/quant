"""2023年以来涨停首板事件数据与次日可交易性的独立可行性研究。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.tushare_limit_incremental import LimitListDuckDBStore, TushareLimitClient
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "limit_up_first_board_event_data_feasibility_v1"
REPORT_PATH = Path("docs/research/limit-up-first-board-event-data-feasibility-v1.md")
START_DATE = "20230101"
RELIABLE_AS_OF = "20260728"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="涨停首板事件数据可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "Tushare日涨跌停榜能否从2023年以来形成覆盖稳定、字段完整、次日行情可见且不过度集中于少数股票的"
        "首板事件样本，从而支持一次冻结的中短周期事件回测"
    ),
    definition={
        "source": "tushare.limit_list_d",
        "period": [START_DATE, RELIABLE_AS_OF],
        "event_scope": {
            "limit_type": "U",
            "first_board_proxy": "open_times_eq_0",
            "exclude_name_contains": ["ST", "退"],
            "outcome_returns_not_inspected": True,
        },
        "next_day_audit": {
            "source": "unified_live_market_view",
            "fields": ["open", "close", "vol", "amount"],
            "only_coverage_and_tradability": True,
        },
        "gate": {
            "trade_date_coverage_min": 0.97,
            "limit_up_events_min": 30000,
            "first_board_events_min": 5000,
            "eligible_events_min": 4500,
            "unique_symbols_min": 1500,
            "covered_months_min": 42,
            "positive_amount_share_min": 0.99,
            "nonnegative_fd_amount_share_min": 0.99,
            "next_day_bar_coverage_min": 0.98,
            "next_day_positive_open_share_min": 0.98,
            "top10_symbol_share_max": 0.05,
        },
        "parameters_fixed_before_cache_backfill": True,
        "promotion_scope": "feasibility_only_no_strategy_registration",
        "methodology_version": "limit_event_coverage_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    normalized_as_of = min(str(as_of_date).replace("-", ""), RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=_data_version(paths, normalized_as_of),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, eligible = _calculate(
            paths,
            normalized_as_of,
            client=client,
        )
        _complete_attempt(attempt, result, eligible)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    client: Any | None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    trade_dates = _load_trade_dates(paths, as_of_date)
    missing = _missing_cache_dates(paths.limit_list_increment_path, trade_dates)
    rows_written = _backfill_missing_dates(
        paths.limit_list_increment_path,
        missing,
        client or TushareLimitClient(),
    )
    events = _load_limit_events(
        paths.limit_list_increment_path,
        START_DATE,
        as_of_date,
    )
    audit, eligible = audit_events(paths, events, trade_dates, as_of_date)
    result = {
        "experiment_id": EXPERIMENT_ID,
        "period": [START_DATE, as_of_date],
        "cache": {
            "requested_trade_dates": len(trade_dates),
            "missing_dates_before": len(missing),
            "rows_written": rows_written,
            "cache_path": str(paths.limit_list_increment_path),
        },
        "audit": audit,
        "gate": {
            "passed": all(audit["checks"].values()),
            "checks": audit["checks"],
        },
        "next_step": (
            "允许冻结一次首板次日事件策略定义"
            if all(audit["checks"].values())
            else "数据门禁未通过，不进入收益回测"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, eligible


def audit_events(
    paths: RuntimePaths,
    events: pd.DataFrame,
    trade_dates: list[str],
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    if events.empty:
        raise ValueError("涨跌停事件缓存为空")
    frame = events.copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    limit_up = frame[frame["limit_type"].eq("U")].copy()
    first_board = limit_up[
        pd.to_numeric(limit_up["open_times"], errors="coerce").fillna(-1).eq(0)
    ].copy()
    names = first_board["name"].fillna("").astype(str)
    eligible = first_board[
        ~names.str.contains("ST|退", case=False, regex=True)
    ].copy()
    next_day = _attach_next_day_bars(paths, eligible, trade_dates, as_of_date)
    cached_dates = set(frame["trade_date"])
    symbol_counts = eligible["ts_code"].value_counts()
    top10_share = (
        float(symbol_counts.head(10).sum() / len(eligible))
        if len(eligible)
        else 1.0
    )
    covered_months = int(eligible["trade_date"].str[:6].nunique())
    date_coverage = (
        len(cached_dates.intersection(trade_dates)) / len(trade_dates)
        if trade_dates
        else 0.0
    )
    next_day_coverage = (
        float(next_day["next_close"].notna().mean())
        if len(next_day)
        else 0.0
    )
    next_day_positive_open = (
        float(
            pd.to_numeric(next_day["next_open"], errors="coerce")
            .fillna(0)
            .gt(0)
            .mean()
        )
        if len(next_day)
        else 0.0
    )
    metrics = {
        "trade_dates": len(trade_dates),
        "cached_trade_dates": len(cached_dates.intersection(trade_dates)),
        "trade_date_coverage": date_coverage,
        "all_events": len(frame),
        "limit_up_events": len(limit_up),
        "first_board_events": len(first_board),
        "eligible_events": len(eligible),
        "unique_symbols": int(eligible["ts_code"].nunique()),
        "covered_months": covered_months,
        "positive_amount_share": float(
            pd.to_numeric(frame["amount"], errors="coerce").fillna(0).gt(0).mean()
        ),
        "nonnegative_fd_amount_share": float(
            pd.to_numeric(frame["fd_amount"], errors="coerce").fillna(-1).ge(0).mean()
        ),
        "next_day_bar_coverage": next_day_coverage,
        "next_day_positive_open_share": next_day_positive_open,
        "top10_symbol_share": top10_share,
    }
    checks = {
        "trade_date_coverage_at_least_97pct": date_coverage >= 0.97,
        "limit_up_events_at_least_30000": len(limit_up) >= 30000,
        "first_board_events_at_least_5000": len(first_board) >= 5000,
        "eligible_events_at_least_4500": len(eligible) >= 4500,
        "unique_symbols_at_least_1500": eligible["ts_code"].nunique() >= 1500,
        "covered_months_at_least_42": covered_months >= 42,
        "positive_amount_share_at_least_99pct": metrics["positive_amount_share"] >= 0.99,
        "nonnegative_fd_amount_share_at_least_99pct": (
            metrics["nonnegative_fd_amount_share"] >= 0.99
        ),
        "next_day_bar_coverage_at_least_98pct": next_day_coverage >= 0.98,
        "next_day_positive_open_share_at_least_98pct": next_day_positive_open >= 0.98,
        "top10_symbol_share_at_most_5pct": top10_share <= 0.05,
    }
    output_columns = [
        "trade_date",
        "ts_code",
        "name",
        "close",
        "pct_chg",
        "amount",
        "fd_amount",
        "open_times",
        "next_trade_date",
        "next_open",
        "next_close",
        "next_vol",
        "next_amount",
    ]
    return {
        "metrics": metrics,
        "checks": checks,
    }, next_day.reindex(columns=output_columns)


def _load_trade_dates(paths: RuntimePaths, as_of_date: str) -> list[str]:
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=START_DATE,
        as_of_date=as_of_date,
    )
    try:
        rows = connection.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [START_DATE, as_of_date],
        ).fetchall()
    finally:
        connection.close()
    return [str(row[0]) for row in rows]


def _missing_cache_dates(path: Path, trade_dates: list[str]) -> list[str]:
    if not path.exists():
        return trade_dates
    with duckdb.connect(str(path), read_only=True) as connection:
        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        if "limit_list_daily" not in tables:
            return trade_dates
        cached = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT trade_date FROM limit_list_daily"
            ).fetchall()
        }
    return [date for date in trade_dates if date not in cached]


def _backfill_missing_dates(
    path: Path,
    trade_dates: list[str],
    client: Any,
    *,
    request_interval_seconds: float = 0.34,
) -> int:
    store = LimitListDuckDBStore(path)
    rows_written = 0
    last_request_at = 0.0
    for index, trade_date in enumerate(trade_dates, start=1):
        for attempt in range(4):
            try:
                elapsed = time.monotonic() - last_request_at
                if elapsed < request_interval_seconds:
                    time.sleep(request_interval_seconds - elapsed)
                rows_written += store.upsert(client.limit_list_d(trade_date))
                last_request_at = time.monotonic()
                break
            except Exception as error:
                last_request_at = time.monotonic()
                if attempt == 3:
                    raise
                wait = 20.0 if "频率超限" in str(error) else 1.0 + attempt
                time.sleep(wait)
        if index % 50 == 0 or index == len(trade_dates):
            print(
                f"limit cache progress={index}/{len(trade_dates)} "
                f"rows={rows_written} last={trade_date}",
                flush=True,
            )
    return rows_written


def _load_limit_events(path: Path, start_date: str, end_date: str) -> pd.DataFrame:
    with duckdb.connect(str(path), read_only=True) as connection:
        return connection.execute(
            """
            SELECT *
            FROM limit_list_daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date, ts_code
            """,
            [start_date, end_date],
        ).fetchdf()


def _attach_next_day_bars(
    paths: RuntimePaths,
    events: pd.DataFrame,
    trade_dates: list[str],
    as_of_date: str,
) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    mapping = pd.DataFrame(
        {
            "trade_date": trade_dates[:-1],
            "next_trade_date": trade_dates[1:],
        }
    )
    selected = events.merge(mapping, on="trade_date", how="left")
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        lookback_start=START_DATE,
        as_of_date=as_of_date,
    )
    try:
        connection.register("selected_limit_events", selected)
        return connection.execute(
            """
            SELECT
                e.*,
                d.open AS next_open,
                d.close AS next_close,
                d.vol AS next_vol,
                d.amount AS next_amount
            FROM selected_limit_events e
            LEFT JOIN daily d
              ON d.ts_code = e.ts_code
             AND d.trade_date = e.next_trade_date
            ORDER BY e.trade_date, e.ts_code
            """
        ).fetchdf()
    finally:
        connection.close()


def render_report(result: dict[str, Any]) -> str:
    metrics = result["audit"]["metrics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 涨停首板事件数据可行性 V1

- 研究区间：{result['period'][0]} 至 {result['period'][1]}。
- 本阶段只审计事件覆盖、字段质量、次日行情和样本集中度，不查看事件后收益。
- 交易日覆盖：{metrics['cached_trade_dates']}/{metrics['trade_dates']}（{metrics['trade_date_coverage']:.2%}）。
- 全部涨停榜事件 / 涨停事件：{metrics['all_events']} / {metrics['limit_up_events']}。
- 首板代理 / 剔除ST退市后：{metrics['first_board_events']} / {metrics['eligible_events']}。
- 唯一股票 / 覆盖月份：{metrics['unique_symbols']} / {metrics['covered_months']}。
- 次日行情覆盖 / 次日正开盘价：{metrics['next_day_bar_coverage']:.2%} / {metrics['next_day_positive_open_share']:.2%}。
- 前10大高频股票占比：{metrics['top10_symbol_share']:.2%}。

## 冻结门槛

{checks}

结论：{result['next_step']}。
"""


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    eligible: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    audit_path = attempt.output_dir / "data_audit.json"
    audit_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sample_path = attempt.output_dir / "eligible_event_sample.csv"
    eligible.head(500).to_csv(sample_path, index=False)
    passed = bool(result["gate"]["passed"])
    failed = [
        name
        for name, value in result["gate"]["checks"].items()
        if not value
    ]
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "涨停首板事件数据门禁通过，可冻结一次事件策略回测"
            if passed
            else f"涨停首板事件数据门禁未通过（{', '.join(failed)}），停止于收益回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "首板事件数据可行性报告"),
            ExperimentArtifact("diagnostics", audit_path, "完整数据门禁"),
            ExperimentArtifact("sample", sample_path, "合格事件前500条样本"),
        ],
    )


def _data_version(paths: RuntimePaths, as_of_date: str) -> str:
    base = paths.base_market_path.stat()
    increment = paths.live_market_increment_path.stat()
    return (
        f"tushare_limit_list_d:{START_DATE}:{as_of_date}:v1|"
        f"base:{base.st_size}:{base.st_mtime_ns}|"
        f"increment:{increment.st_size}:{increment.st_mtime_ns}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
