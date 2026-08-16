"""审计首板策略“盘中触板即开盘不可买”的保守执行假设。"""

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

from examples.limit_up_first_board_strategy_study import (
    RELIABLE_AS_OF,
    STUDY_START,
    _load_events,
    build_daily_targets,
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


EXPERIMENT_ID = "limit_up_first_board_execution_assumption_audit_v1"
REPORT_PATH = Path(
    "docs/research/limit-up-first-board-execution-assumption-audit-v1.md"
)

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="首板次日开盘成交口径审计 V1",
    category="execution_assumption_audit",
    hypothesis=(
        "公共M0的涨停拦截使用全天最高价，会把开盘可买、盘中才触板的样本误判为不可买；"
        "该差异是否足以使首板策略原回测只能解释为保守下界"
    ),
    definition={
        "dependency": "limit_up_first_board_seal_strength_v1",
        "period": [STUDY_START, RELIABLE_AS_OF],
        "sample": "same_daily_top10_seal_strength_targets",
        "current_rule": "next_day_high_ge_board_upper_blocks_buy",
        "point_in_time_rule": "next_day_open_ge_board_upper_blocks_buy",
        "price_source": "unadjusted_daily_open_high_pre_close",
        "return_outcomes_loaded": False,
        "gate": {
            "pair_coverage_min": 0.99,
            "false_block_share_min": 0.05,
        },
        "promotion_scope": "audit_only_no_strategy_registration",
        "methodology_version": "first_board_open_fill_audit_v1",
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
        result, rows = _calculate(paths, normalized_as_of)
        _complete_attempt(attempt, result, rows)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(
    paths: RuntimePaths,
    as_of_date: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    events = _load_events(paths.limit_list_increment_path, as_of_date)
    _, selected = build_daily_targets(events, ranking="seal_strength")
    calendar = _load_calendar(paths.base_market_path, as_of_date)
    pairs = attach_execution_dates(selected, calendar)
    rows = load_execution_bars(paths.base_market_path, pairs)
    audited = classify_buy_blocks(rows)
    covered = audited["open"].notna() & audited["pre_close"].notna()
    current_block = audited["current_model_blocks"].fillna(False)
    point_in_time_block = audited["open_rule_blocks"].fillna(False)
    false_block = current_block & ~point_in_time_block
    denominator = int(covered.sum())
    metrics = {
        "selected_pairs": len(audited),
        "covered_pairs": denominator,
        "pair_coverage": denominator / len(audited) if len(audited) else 0.0,
        "current_model_block_count": int((current_block & covered).sum()),
        "current_model_block_share": (
            float((current_block & covered).sum() / denominator)
            if denominator
            else 0.0
        ),
        "open_rule_block_count": int((point_in_time_block & covered).sum()),
        "open_rule_block_share": (
            float((point_in_time_block & covered).sum() / denominator)
            if denominator
            else 0.0
        ),
        "false_block_count": int((false_block & covered).sum()),
        "false_block_share": (
            float((false_block & covered).sum() / denominator)
            if denominator
            else 0.0
        ),
    }
    by_year = {}
    for year, frame in audited.loc[covered].groupby(
        audited.loc[covered, "signal_date"].str[:4]
    ):
        by_year[str(year)] = summarize_classification(frame)
    checks = {
        "pair_coverage_at_least_99pct": metrics["pair_coverage"] >= 0.99,
        "false_block_share_at_least_5pct": metrics["false_block_share"] >= 0.05,
    }
    result = {
        "experiment_id": EXPERIMENT_ID,
        "period": [STUDY_START, as_of_date],
        "metrics": metrics,
        "by_signal_year": by_year,
        "gate": {"passed": all(checks.values()), "checks": checks},
        "conclusion": (
            "公共M0对该事件策略存在显著的开盘买入误拦截，原结果仅可视为保守下界"
            if all(checks.values())
            else "未发现足以解释原结果的开盘买入误拦截"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, audited


def attach_execution_dates(
    selected: pd.DataFrame,
    calendar: list[str],
) -> pd.DataFrame:
    next_dates = dict(zip(calendar[:-1], calendar[1:]))
    pairs = selected[["trade_date", "ts_code"]].copy()
    pairs["signal_date"] = pairs["trade_date"].astype(str)
    pairs["execution_date"] = pairs["signal_date"].map(next_dates)
    return pairs.dropna(subset=["execution_date"])[
        ["signal_date", "execution_date", "ts_code"]
    ].reset_index(drop=True)


def classify_buy_blocks(rows: pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy()
    code = frame["ts_code"].astype(str)
    name = frame["st_name"].fillna("").astype(str)
    rate = pd.Series(0.10, index=frame.index)
    rate.loc[name.str.contains("ST|退", case=False, regex=True)] = 0.05
    rate.loc[code.str.startswith(("300", "301", "688", "689"))] = 0.20
    rate.loc[code.str.startswith(("8", "4", "920"))] = 0.30
    pre_close = pd.to_numeric(frame["pre_close"], errors="coerce")
    upper = (pre_close * (1.0 + rate)).round(2)
    open_price = pd.to_numeric(frame["open"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    frame["board_upper"] = upper
    frame["current_model_blocks"] = high.notna() & high.ge(upper - 1e-6)
    frame["open_rule_blocks"] = (
        open_price.notna() & open_price.ge(upper - 1e-6)
    )
    frame["false_block"] = (
        frame["current_model_blocks"] & ~frame["open_rule_blocks"]
    )
    return frame


def summarize_classification(frame: pd.DataFrame) -> dict[str, float | int]:
    total = len(frame)
    return {
        "pairs": total,
        "current_model_block_share": (
            float(frame["current_model_blocks"].mean()) if total else 0.0
        ),
        "open_rule_block_share": (
            float(frame["open_rule_blocks"].mean()) if total else 0.0
        ),
        "false_block_share": (
            float(frame["false_block"].mean()) if total else 0.0
        ),
    }


def load_execution_bars(
    base_path: Path,
    pairs: pd.DataFrame,
) -> pd.DataFrame:
    with duckdb.connect(str(base_path), read_only=True) as connection:
        connection.register("selected_pairs", pairs)
        return connection.execute(
            """
            SELECT
                p.signal_date,
                p.execution_date,
                p.ts_code,
                d.open,
                d.high,
                d.pre_close,
                st.name AS st_name
            FROM selected_pairs p
            LEFT JOIN daily d
              ON d.trade_date = p.execution_date
             AND d.ts_code = p.ts_code
            LEFT JOIN stock_st st
              ON st.trade_date = p.execution_date
             AND st.ts_code = p.ts_code
            ORDER BY p.signal_date, p.ts_code
            """
        ).fetchdf()


def _load_calendar(base_path: Path, as_of_date: str) -> list[str]:
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
    rows: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    metrics_path = attempt.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sample_path = attempt.output_dir / "classified_execution_pairs.csv"
    rows.to_csv(sample_path, index=False)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_EXECUTION_AUDIT" if passed else "REJECTED",
        decision_reason=result["conclusion"],
        artifacts=[
            ExperimentArtifact("summary", summary, "首板执行口径审计报告"),
            ExperimentArtifact("metrics", metrics_path, "执行口径审计指标"),
            ExperimentArtifact("classified_pairs", sample_path, "逐样本分类"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    year_rows = "\n".join(
        "| {year} | {pairs:,} | {current:.2%} | {open_rule:.2%} | {false:.2%} |".format(
            year=year,
            pairs=item["pairs"],
            current=item["current_model_block_share"],
            open_rule=item["open_rule_block_share"],
            false=item["false_block_share"],
        )
        for year, item in result["by_signal_year"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    return f"""# 首板次日开盘成交口径审计 V1

- 实验：`{EXPERIMENT_ID}`
- 区间：`{result['period'][0]}` 至 `{result['period'][1]}`
- 结论：**{result['conclusion']}**

## 总体结果

- 目标样本：{metrics['selected_pairs']:,}
- 行情覆盖：{metrics['pair_coverage']:.4%}
- 公共 M0（全天最高价触板即拦截）买入拦截率：{metrics['current_model_block_share']:.4%}
- 时点正确口径（开盘价已封板才拦截）买入拦截率：{metrics['open_rule_block_share']:.4%}
- 开盘可买但被公共 M0 误拦截：{metrics['false_block_count']:,} 笔，{metrics['false_block_share']:.4%}

## 分年

| 信号年 | 样本 | 公共 M0 拦截 | 开盘封板拦截 | 误拦截 |
|---|---:|---:|---:|---:|
{year_rows}

## 门禁

{checks}

本审计不读取收益结果、不改写原实验，也不注册策略。它只判断首轮回测采用的成交拦截口径是否适合开盘成交事件策略。
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
