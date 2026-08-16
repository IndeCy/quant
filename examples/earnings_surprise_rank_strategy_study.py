"""修正头部同分后的标准化意外盈利事件策略研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.earnings_surprise_strategy_report import render_report
from examples.earnings_surprise_strategy_study import (
    calculate_strategy,
    _data_version,
)
from factors.earnings_surprise import score_earnings_surprise_rank_frame
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


STRATEGY_ID = "earnings_surprise_event_rank_v2"
REPORT_PATH = Path("docs/research/earnings-surprise-event-rank-v2.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=STRATEGY_ID,
    name="标准化意外盈利事件秩策略 V2",
    category="factor_strategy",
    hypothesis="消除缩尾头部同分后，SUE原始秩是否形成稳定且独立的公告后Alpha",
    definition={
        "predecessor": {
            "experiment_id": "earnings_surprise_event_v1",
            "outcome": "REJECTED",
            "method_issue": (
                "winsorized_top_one_percent_tied_and_symbol_sorted"
            ),
        },
        "only_change": {
            "v1": "winsorize_1_99_then_percentile_rank",
            "v2": "raw_sue_percentile_rank",
            "reason": (
                "SUE_is_already_time_series_standardized_and_rank_is_robust"
            ),
        },
        "unchanged": {
            "history_observations": 8,
            "event_age_days": 90,
            "positive_eps_and_surprise": True,
            "top_n": 20,
            "event_schedule": "carry_when_unconstructible",
            "universe": (
                "listed_3y_ex_st_delisted_suspended_bottom20_amount"
            ),
            "risk_overlay": "vol20_gt45pct_to30pct",
            "execution": "qfq_m0_t1_5bps",
            "evaluation": (
                "same_train_validation_locked_gate_as_v1"
            ),
        },
        "single_method_correction_only": True,
        "stop_direction_if_rejected": True,
        "parameters_fixed_before_backtest": True,
        "methodology_version": "sue_raw_rank_v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """申请新定义指纹后才执行修正版回测。"""
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
    """保持所有其他口径不变，仅替换SUE排名方式。"""
    result = calculate_strategy(
        paths,
        as_of_date,
        strategy_id=STRATEGY_ID,
        scorer=score_earnings_surprise_rank_frame,
    )
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            result["period_metrics"],
            result["annual_metrics"],
            result["gate"],
            float(result["quality_return_correlation"]),
            result["diagnostics"],
            str(result["latest_date"]),
            title="标准化意外盈利事件秩策略 V2",
            transform_description="直接按原始SUE做横截面百分位秩",
        ),
        encoding="utf-8",
    )
    return {**result, "report_path": str(report_path)}


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """归档唯一一次方法修正，失败后终止SUE方向。"""
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        Path(str(result["report_path"])).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    holdings_path = attempt.output_dir / "latest_holdings.csv"
    pd.DataFrame(result["latest_holdings"]).to_csv(
        holdings_path,
        index=False,
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED" if passed else "REJECTED",
        decision_reason=(
            "SUE原始秩通过固定门槛，允许进入独立确认"
            if passed
            else "SUE原始秩仍未通过门槛，终止SUE方向"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "SUE V2报告"),
            ExperimentArtifact(
                "holdings",
                holdings_path,
                "SUE V2最新Top20",
            ),
        ],
    )


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
