"""涨跌停家数五日情绪状态的周频数据可行性审计。"""

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

from examples.limit_down_weekly_reversal_feasibility_study import (
    RELIABLE_AS_OF,
    STUDY_START,
    weekly_signal_dates,
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


EXPERIMENT_ID = "limit_event_five_day_sentiment_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/limit-event-five-day-sentiment-data-feasibility-v1.md"
)

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="涨跌停五日情绪周频状态数据可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "非ST涨停与跌停家数差占比的五日均值，能否形成覆盖完整、事件量充足且状态"
        "分布非退化的A股周频风险偏好指标"
    ),
    definition={
        "source": "tushare.limit_list_d_cache",
        "period": [STUDY_START, RELIABLE_AS_OF],
        "daily_score": "(limit_up_count-limit_down_count)/(up+down)",
        "smoothing": "trailing_5_trading_day_mean",
        "signal": "last_trading_day_of_week",
        "exclude_name_contains": ["ST", "退"],
        "outcome_returns_loaded": False,
        "gate": {
            "weekly_coverage_min": 0.99,
            "nonzero_event_week_share_min": 0.95,
            "median_daily_up_down_events_min": 20,
            "sentiment_q90_minus_q10_min": 0.30,
            "unique_weekly_values_min": 100,
        },
        "promotion_scope": "feasibility_only_no_strategy_registration",
        "methodology_version": "limit_event_sentiment_5d_v1",
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
        result, weekly = calculate(paths, normalized_as_of)
        complete_attempt(attempt, result, weekly)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    calendar = load_calendar(paths.base_market_path, as_of_date)
    daily = load_daily_sentiment(
        paths.limit_list_increment_path,
        calendar,
        as_of_date,
    )
    signal_dates = weekly_signal_dates(calendar)
    weekly = daily[daily["trade_date"].isin(signal_dates)].copy()
    sentiment = pd.to_numeric(weekly["sentiment_5d"], errors="coerce")
    q10 = float(sentiment.quantile(0.10))
    q90 = float(sentiment.quantile(0.90))
    metrics = {
        "expected_weeks": len(signal_dates),
        "observed_weeks": len(weekly),
        "weekly_coverage": len(weekly) / len(signal_dates),
        "nonzero_event_week_share": float(weekly["event_count_5d"].gt(0).mean()),
        "median_daily_up_down_events": float(daily["event_count"].median()),
        "sentiment_min": float(sentiment.min()),
        "sentiment_q10": q10,
        "sentiment_median": float(sentiment.median()),
        "sentiment_q90": q90,
        "sentiment_max": float(sentiment.max()),
        "sentiment_q90_minus_q10": q90 - q10,
        "unique_weekly_values": int(sentiment.nunique()),
    }
    checks = {
        "weekly_coverage_at_least_99pct": metrics["weekly_coverage"] >= 0.99,
        "nonzero_event_week_share_at_least_95pct": (
            metrics["nonzero_event_week_share"] >= 0.95
        ),
        "median_daily_events_at_least_20": (
            metrics["median_daily_up_down_events"] >= 20
        ),
        "sentiment_q90_minus_q10_at_least_30pct": (
            metrics["sentiment_q90_minus_q10"] >= 0.30
        ),
        "unique_weekly_values_at_least_100": (
            metrics["unique_weekly_values"] >= 100
        ),
    }
    passed = all(checks.values())
    result = {
        "experiment_id": EXPERIMENT_ID,
        "period": [STUDY_START, as_of_date],
        "metrics": metrics,
        "gate": {"passed": passed, "checks": checks},
        "decision": (
            "CONTINUE_TO_FIXED_REGIME_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, weekly


def load_daily_sentiment(
    limit_path: Path,
    calendar: list[str],
    as_of_date: str,
) -> pd.DataFrame:
    dates = pd.DataFrame({"trade_date": calendar})
    with duckdb.connect(str(limit_path), read_only=True) as connection:
        connection.register("expected_dates", dates)
        return connection.execute(
            """
            WITH counts AS (
                SELECT
                    d.trade_date,
                    COUNT(*) FILTER(
                        WHERE e.limit_type = 'U'
                          AND COALESCE(e.name, '') NOT LIKE '%ST%'
                          AND COALESCE(e.name, '') NOT LIKE '%退%'
                    ) AS up_count,
                    COUNT(*) FILTER(
                        WHERE e.limit_type = 'D'
                          AND COALESCE(e.name, '') NOT LIKE '%ST%'
                          AND COALESCE(e.name, '') NOT LIKE '%退%'
                    ) AS down_count
                FROM expected_dates d
                LEFT JOIN limit_list_daily e USING(trade_date)
                WHERE d.trade_date BETWEEN ? AND ?
                GROUP BY d.trade_date
            ),
            scored AS (
                SELECT
                    *,
                    up_count + down_count AS event_count,
                    CASE
                        WHEN up_count + down_count > 0
                        THEN CAST(up_count - down_count AS DOUBLE)
                             / (up_count + down_count)
                        ELSE 0.0
                    END AS daily_sentiment
                FROM counts
            )
            SELECT
                *,
                AVG(daily_sentiment) OVER (
                    ORDER BY trade_date
                    ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                ) AS sentiment_5d,
                SUM(event_count) OVER (
                    ORDER BY trade_date
                    ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                ) AS event_count_5d
            FROM scored
            ORDER BY trade_date
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


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    weekly: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    weekly_path = attempt.output_dir / "weekly_sentiment.csv"
    weekly.to_csv(weekly_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "涨跌停五日情绪覆盖与分布通过，可进入一次固定状态回测"
            if passed
            else "涨跌停五日情绪覆盖、事件量或分布不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "涨跌停情绪数据门禁报告"),
            ExperimentArtifact("metrics", metrics_path, "数据门禁指标"),
            ExperimentArtifact("weekly_sentiment", weekly_path, "周频情绪状态"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    m = result["metrics"]
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    return f"""# 涨跌停五日情绪周频状态数据可行性 V1

- 区间：{result['period'][0]} 至 {result['period'][1]}
- 周覆盖：{m['observed_weeks']} / {m['expected_weeks']}（{m['weekly_coverage']:.2%}）
- 日涨跌停事件中位数：{m['median_daily_up_down_events']:.0f}
- 情绪 Min/Q10/Median/Q90/Max：{m['sentiment_min']:.3f} /
  {m['sentiment_q10']:.3f} / {m['sentiment_median']:.3f} /
  {m['sentiment_q90']:.3f} / {m['sentiment_max']:.3f}

## 冻结门禁

{checks}

## 结论

`{result['decision']}`。本阶段不读取资产后续收益、不回测、不注册策略。
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
