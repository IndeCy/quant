"""全A站上60日均线宽度的周频状态数据可行性审计。"""

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


EXPERIMENT_ID = "a_share_ma60_breadth_regime_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/a-share-ma60-breadth-regime-data-feasibility-v1.md"
)
FETCH_START = "20140901"
STUDY_START = "20150101"
RELIABLE_AS_OF = "20260615"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="全A MA60 宽度周频状态数据可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "全A非ST可交易股票中站上60日均线的比例，能否形成覆盖完整、截面足够广且状态"
        "分布非退化的周频风险开关"
    ),
    definition={
        "source": "daily_adj_cache_qfq",
        "period": [STUDY_START, RELIABLE_AS_OF],
        "universe": "non_st_positive_volume_with_60_observations",
        "indicator": "share_close_qfq_ge_ma60_qfq",
        "signal": "last_trading_day_of_week",
        "outcome_returns_loaded": False,
        "gate": {
            "weekly_coverage_min": 0.99,
            "median_universe_min": 2500,
            "minimum_universe_min": 1500,
            "breadth_q90_minus_q10_min": 0.20,
            "breadth_range_valid": [0.0, 1.0],
        },
        "promotion_scope": "feasibility_only_no_strategy_registration",
        "methodology_version": "ma60_breadth_weekly_v1",
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
    daily = load_daily_breadth(paths.base_market_path, as_of_date)
    weekly = select_weekly_last(daily)
    expected = expected_weekly_dates(paths.base_market_path, as_of_date)
    coverage = len(set(weekly["trade_date"]) & set(expected)) / len(expected)
    breadth = pd.to_numeric(weekly["breadth_ma60"], errors="coerce")
    q10 = float(breadth.quantile(0.10))
    q90 = float(breadth.quantile(0.90))
    metrics = {
        "expected_weeks": len(expected),
        "observed_weeks": len(weekly),
        "weekly_coverage": coverage,
        "median_universe": float(weekly["universe_count"].median()),
        "minimum_universe": int(weekly["universe_count"].min()),
        "breadth_min": float(breadth.min()),
        "breadth_q10": q10,
        "breadth_median": float(breadth.median()),
        "breadth_q90": q90,
        "breadth_max": float(breadth.max()),
        "breadth_q90_minus_q10": q90 - q10,
    }
    checks = {
        "weekly_coverage_at_least_99pct": coverage >= 0.99,
        "median_universe_at_least_2500": metrics["median_universe"] >= 2500,
        "minimum_universe_at_least_1500": metrics["minimum_universe"] >= 1500,
        "breadth_q90_minus_q10_at_least_20pct": (
            metrics["breadth_q90_minus_q10"] >= 0.20
        ),
        "breadth_within_zero_one": (
            metrics["breadth_min"] >= 0 and metrics["breadth_max"] <= 1
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


def load_daily_breadth(base_path: Path, as_of_date: str) -> pd.DataFrame:
    with duckdb.connect(str(base_path), read_only=True) as connection:
        return connection.execute(
            """
            WITH source AS (
                SELECT
                    a.trade_date,
                    a.ts_code,
                    CAST(a.close_qfq AS DOUBLE) AS close_qfq,
                    CAST(d.vol AS DOUBLE) AS vol,
                    COALESCE(st.name, '') AS st_name
                FROM daily_adj_cache a
                JOIN daily d USING(trade_date, ts_code)
                LEFT JOIN stock_st st USING(trade_date, ts_code)
                WHERE a.trade_date BETWEEN ? AND ?
                  AND a.close_qfq > 0
                  AND d.vol > 0
                  AND COALESCE(st.name, '') NOT LIKE '%ST%'
                  AND COALESCE(st.name, '') NOT LIKE '%退%'
            ),
            rolling AS (
                SELECT
                    *,
                    AVG(close_qfq) OVER (
                        PARTITION BY ts_code ORDER BY trade_date
                        ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                    ) AS ma60,
                    COUNT(*) OVER (
                        PARTITION BY ts_code ORDER BY trade_date
                        ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                    ) AS observations
                FROM source
            )
            SELECT
                trade_date,
                COUNT(*) AS universe_count,
                AVG(CASE WHEN close_qfq >= ma60 THEN 1.0 ELSE 0.0 END)
                    AS breadth_ma60
            FROM rolling
            WHERE trade_date >= ?
              AND observations = 60
            GROUP BY trade_date
            ORDER BY trade_date
            """,
            [FETCH_START, as_of_date, STUDY_START],
        ).fetchdf()


def select_weekly_last(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["trade_date"].astype(str))
    frame["week"] = frame["date"].dt.to_period("W-FRI")
    return (
        frame.sort_values("date")
        .groupby("week", sort=True)
        .tail(1)
        .drop(columns=["date", "week"])
        .reset_index(drop=True)
    )


def expected_weekly_dates(base_path: Path, as_of_date: str) -> list[str]:
    with duckdb.connect(str(base_path), read_only=True) as connection:
        dates = connection.execute(
            """
            SELECT DISTINCT trade_date
            FROM daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [STUDY_START, as_of_date],
        ).fetchdf()
    return select_weekly_last(
        dates.assign(universe_count=1, breadth_ma60=0.5)
    )["trade_date"].astype(str).tolist()


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
    weekly_path = attempt.output_dir / "weekly_breadth.csv"
    weekly.to_csv(weekly_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "全A MA60宽度覆盖与分布通过，可进入一次固定状态回测"
            if passed
            else "全A MA60宽度覆盖或分布不足，终止于收益回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "全A宽度数据门禁报告"),
            ExperimentArtifact("metrics", metrics_path, "数据门禁指标"),
            ExperimentArtifact("weekly_breadth", weekly_path, "周频宽度状态"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    m = result["metrics"]
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    return f"""# 全A MA60 宽度周频状态数据可行性 V1

- 区间：{result['period'][0]} 至 {result['period'][1]}
- 周覆盖：{m['observed_weeks']} / {m['expected_weeks']}（{m['weekly_coverage']:.2%}）
- 有效股票数中位/最少：{m['median_universe']:.0f} / {m['minimum_universe']}
- 宽度 Min/Q10/Median/Q90/Max：{m['breadth_min']:.2%} /
  {m['breadth_q10']:.2%} / {m['breadth_median']:.2%} /
  {m['breadth_q90']:.2%} / {m['breadth_max']:.2%}

## 冻结门禁

{checks}

## 结论

`{result['decision']}`。本阶段不读取资产后续收益、不回测、不注册策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    stat = paths.base_market_path.stat()
    return f"base_market:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
