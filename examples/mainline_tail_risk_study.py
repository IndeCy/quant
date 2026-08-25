"""主线链动独立Alpha的尾部集中度与回撤恢复法医研究。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sqlite3
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.mainline_tail_risk_metrics import (
    build_tail_profile,
    evaluate_tail_gate,
)
from examples.mainline_tail_risk_report import render_report
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "mainline_chain_tail_risk_forensics_v1"
REPORT_PATH = Path("docs/research/mainline-chain-tail-risk-forensics-v1.md")
STRATEGIES = {
    "mainline_chain_factor_v1": "Mainline Chain",
    "quality_overlay": "Quality Alpha",
}
EPISODE_THRESHOLD = -0.10
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="主线链动尾部风险法医 V1",
    category="strategy_risk_attribution",
    hypothesis="低相关主线Alpha的高收益是否能通过收益广度、尾部损失和一年内恢复门槛",
    definition={
        "strategies": STRATEGIES,
        "source": "monitoring_strategy_nav_daily_net_of_execution_cost",
        "history": "strict_common_dates_no_fill",
        "drawdown_episode_threshold": EPISODE_THRESHOLD,
        "tail_metrics": {
            "value_at_risk": 0.95,
            "expected_shortfall": 0.95,
            "best_day_removal_count": 10,
            "positive_log_return_contribution_count": 10,
            "maximum_underwater_days": "peak_to_recovery_or_asof",
        },
        "frozen_gate": {
            "max_drawdown_floor": -0.35,
            "maximum_underwater_days": 252,
            "top10_positive_log_contribution_max": 0.35,
            "annual_return_without_best10_positive": True,
            "expected_shortfall_floor": -0.04,
            "positive_year_share_min": 0.60,
        },
        "existing_regime_filter_result": (
            "mainline_risk_positive_conditional_70_30_v1_rejected"
        ),
        "no_strategy_state_or_risk_change": True,
        "methodology_version": "v1_2_underwater_gate_corrected",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记固定尾部门槛后读取策略净值。"""
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
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """严格共同日期比较Mainline与Quality的尾部风险。"""
    histories = _load_histories(paths, as_of_date)
    common: pd.DataFrame | None = None
    for strategy_id, label in STRATEGIES.items():
        frame = histories[strategy_id]
        if frame.empty or frame["trade_date"].duplicated().any():
            raise ValueError(f"invalid strategy history: {strategy_id}")
        part = frame[["trade_date", "nav"]].rename(columns={"nav": label})
        common = (
            part
            if common is None
            else common.merge(
                part,
                on="trade_date",
                how="inner",
                validate="one_to_one",
            )
        )
    if common is None or len(common) < 1_000:
        raise ValueError("mainline tail study requires 1000 common days")
    common = common.sort_values("trade_date")
    index = pd.to_datetime(common["trade_date"], format="%Y%m%d")
    profiles = {
        label: build_tail_profile(
            pd.Series(
                common[label].astype(float).to_numpy(),
                index=index,
            ),
            episode_threshold=EPISODE_THRESHOLD,
        )
        for label in STRATEGIES.values()
    }
    gate = evaluate_tail_gate(profiles["Mainline Chain"])
    result = {
        "start_date": str(common["trade_date"].min()),
        "latest_date": str(common["trade_date"].max()),
        "common_days": int(len(common)),
        "profiles": profiles,
        "gate": gate,
        "decision": (
            "TAIL_RISK_OBSERVATION_GATE_PASSED"
            if gate["passed"]
            else "INDEPENDENT_ALPHA_NOT_RISK_STABLE"
        ),
        "explanation": (
            "主线收益具备足够广度且尾部风险可在一年内恢复，可继续长期独立观察。"
            if gate["passed"]
            else "主线虽与Quality低相关，但至少一个尾部或恢复门槛失败，暂不能视为稳定Alpha。"
        ),
        "reused": False,
    }
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result


def _load_histories(
    paths: RuntimePaths,
    as_of_date: str,
) -> dict[str, pd.DataFrame]:
    """从统一监控事实表读取净成本净值。"""
    histories: dict[str, pd.DataFrame] = {}
    with sqlite3.connect(paths.monitoring_path) as connection:
        for strategy_id in STRATEGIES:
            histories[strategy_id] = pd.read_sql_query(
                """
                SELECT trade_date, nav
                FROM strategy_nav_daily
                WHERE strategy_id = ? AND trade_date <= ?
                ORDER BY trade_date
                """,
                connection,
                params=[strategy_id, as_of_date],
            )
    return histories


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """登记尾部法医结论，不改变策略观察状态。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            f"主线链动尾部法医完成：{result['decision']}"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "主线尾部风险报告"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """绑定监控库和两个策略声明版本。"""
    parts: list[str] = []
    for label, path in [
        ("monitoring", paths.monitoring_path),
        (
            "mainline_config",
            paths.config_dir / "strategies" / "mainline_chain_factor_v1.json",
        ),
        (
            "quality_config",
            paths.config_dir / "strategies" / "quality_overlay.json",
        ),
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
