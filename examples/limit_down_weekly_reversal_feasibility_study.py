"""近五日跌停事件周频反转候选的数据可行性审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "limit_down_weekly_reversal_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/limit-down-weekly-reversal-data-feasibility-v1.md"
)
STUDY_START = "20230101"
RELIABLE_AS_OF = "20260615"
LOOKBACK_DAYS = 5
TOP_N = 20

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="跌停流动性释放周频反转数据可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "近五个交易日收盘跌停、非ST股票能否在周末形成数量稳定、次周开盘行情完整且"
        "不过度集中于少数股票的中频反转候选池"
    ),
    definition={
        "source": "tushare.limit_list_d_cache",
        "period": [STUDY_START, RELIABLE_AS_OF],
        "event": {
            "limit_type": "D",
            "lookback_trading_days": LOOKBACK_DAYS,
            "exclude_name_contains": ["ST", "退"],
            "deduplicate": "latest_event_per_symbol_per_signal",
        },
        "signal": "last_trading_day_of_week",
        "execution_audit": "next_trading_day_open_coverage_only",
        "outcome_returns_loaded": False,
        "gate": {
            "nonempty_week_share_min": 0.85,
            "median_candidates_min": TOP_N,
            "weeks_with_top_n_share_min": 0.60,
            "unique_symbols_min": 800,
            "next_open_coverage_min": 0.98,
            "top10_symbol_share_max": 0.05,
        },
        "promotion_scope": "feasibility_only_no_strategy_registration",
        "methodology_version": "limit_down_weekly_pool_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    normalized_as_of = min(str(as_of_date).replace("-", ""), RELIABLE_AS_OF)
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=normalized_as_of,
        data_version=_data_version(paths),
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result, candidates = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, candidates)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    events = load_events(paths.limit_list_increment_path, as_of_date)
    calendar = load_calendar(paths.base_market_path, as_of_date)
    signal_dates = weekly_signal_dates(calendar)
    candidates = build_weekly_candidates(events, signal_dates, calendar)
    audited = attach_next_open(
        paths.base_market_path,
        candidates,
        calendar,
    )
    counts = audited.groupby("signal_date").size().reindex(
        signal_dates,
        fill_value=0,
    )
    symbol_counts = audited["ts_code"].value_counts()
    top10_share = (
        float(symbol_counts.head(10).sum() / len(audited))
        if len(audited)
        else 1.0
    )
    metrics = {
        "signal_weeks": len(signal_dates),
        "nonempty_week_share": float(counts.gt(0).mean()),
        "median_candidates": float(counts.median()),
        "minimum_candidates": int(counts.min()),
        "weeks_with_top_n_share": float(counts.ge(TOP_N).mean()),
        "event_rows": len(audited),
        "unique_symbols": int(audited["ts_code"].nunique()),
        "next_open_coverage": float(
            pd.to_numeric(audited["next_open"], errors="coerce")
            .gt(0)
            .mean()
        ),
        "top10_symbol_share": top10_share,
    }
    checks = {
        "nonempty_week_share_at_least_85pct": (
            metrics["nonempty_week_share"] >= 0.85
        ),
        "median_candidates_at_least_20": (
            metrics["median_candidates"] >= TOP_N
        ),
        "weeks_with_top20_at_least_60pct": (
            metrics["weeks_with_top_n_share"] >= 0.60
        ),
        "unique_symbols_at_least_800": metrics["unique_symbols"] >= 800,
        "next_open_coverage_at_least_98pct": (
            metrics["next_open_coverage"] >= 0.98
        ),
        "top10_symbol_share_at_most_5pct": top10_share <= 0.05,
    }
    passed = all(checks.values())
    result = {
        "experiment_id": EXPERIMENT_ID,
        "period": [STUDY_START, as_of_date],
        "metrics": metrics,
        "gate": {"passed": passed, "checks": checks},
        "decision": (
            "CONTINUE_TO_FIXED_WEEKLY_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, audited


def weekly_signal_dates(calendar: list[str]) -> list[str]:
    frame = pd.DataFrame({"trade_date": pd.to_datetime(calendar)})
    frame["week"] = frame["trade_date"].dt.to_period("W-FRI")
    return (
        frame.groupby("week", sort=True)["trade_date"]
        .max()
        .dt.strftime("%Y%m%d")
        .tolist()
    )


def build_weekly_candidates(
    events: pd.DataFrame,
    signal_dates: list[str],
    calendar: list[str],
) -> pd.DataFrame:
    frame = events.copy()
    frame["trade_date"] = frame["trade_date"].astype(str)
    frame["name"] = frame["name"].fillna("").astype(str)
    frame = frame[
        frame["limit_type"].eq("D")
        & ~frame["name"].str.contains("ST|退", case=False, regex=True)
    ].copy()
    positions = {date: index for index, date in enumerate(calendar)}
    parts = []
    for signal_date in signal_dates:
        end = positions[signal_date]
        allowed = set(calendar[max(0, end - LOOKBACK_DAYS + 1) : end + 1])
        current = frame[frame["trade_date"].isin(allowed)].copy()
        if current.empty:
            continue
        current = (
            current.sort_values(
                ["trade_date", "ts_code"],
                ascending=[False, True],
            )
            .drop_duplicates("ts_code", keep="first")
            .copy()
        )
        current["signal_date"] = signal_date
        parts.append(current)
    if not parts:
        return frame.assign(signal_date=pd.Series(dtype=str))
    return pd.concat(parts, ignore_index=True)


def attach_next_open(
    base_path: Path,
    candidates: pd.DataFrame,
    calendar: list[str],
) -> pd.DataFrame:
    next_dates = dict(zip(calendar[:-1], calendar[1:]))
    pairs = candidates.copy()
    pairs["execution_date"] = pairs["signal_date"].map(next_dates)
    pairs = pairs.dropna(subset=["execution_date"])
    with duckdb.connect(str(base_path), read_only=True) as connection:
        connection.register("event_pairs", pairs)
        return connection.execute(
            """
            SELECT p.*, d.open AS next_open
            FROM event_pairs p
            LEFT JOIN daily d
              ON d.trade_date = p.execution_date
             AND d.ts_code = p.ts_code
            ORDER BY p.signal_date, p.ts_code
            """
        ).fetchdf()


def load_events(path: Path, as_of_date: str) -> pd.DataFrame:
    with duckdb.connect(str(path), read_only=True) as connection:
        return connection.execute(
            """
            SELECT *
            FROM limit_list_daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date, ts_code
            """,
            [STUDY_START, as_of_date],
        ).fetchdf()


def load_calendar(base_path: Path, as_of_date: str) -> list[str]:
    with duckdb.connect(str(base_path), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [STUDY_START, as_of_date],
        ).fetchall()
    return [str(row[0]) for row in rows]


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    candidates: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    candidates_path = attempt.output_dir / "weekly_candidates.csv"
    candidates.to_csv(candidates_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "跌停周频候选覆盖与次日开盘行情通过，可进入一次固定回测"
            if passed
            else "跌停周频候选覆盖或次日行情不足，终止于收益回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "跌停周频数据门禁报告"),
            ExperimentArtifact("metrics", metrics_path, "数据门禁指标"),
            ExperimentArtifact("weekly_candidates", candidates_path, "周频候选"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    return f"""# 跌停流动性释放周频反转数据可行性 V1

- 区间：{result['period'][0]} 至 {result['period'][1]}
- 周信号数：{metrics['signal_weeks']}
- 非空周占比：{metrics['nonempty_week_share']:.2%}
- 候选数中位/最少：{metrics['median_candidates']:.0f} / {metrics['minimum_candidates']}
- 至少20只候选周占比：{metrics['weeks_with_top_n_share']:.2%}
- 唯一股票：{metrics['unique_symbols']}
- 次周开盘覆盖：{metrics['next_open_coverage']:.2%}
- Top10股票事件占比：{metrics['top10_symbol_share']:.2%}

## 冻结门禁

{checks}

## 结论

`{result['decision']}`。本阶段未读取后续收益、未回测、未注册策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    parts = []
    for label, path in [
        ("base_market", paths.base_market_path),
        ("limit_cache", paths.limit_list_increment_path),
    ]:
        stat = path.stat()
        parts.append(f"{label}:{stat.st_size}:{stat.st_mtime_ns}")
    return "|".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
