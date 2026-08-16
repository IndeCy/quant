"""板块起飞证据的状态转移审计。

V1 已否决“证据分越高、起飞概率越高”的单调假设。本审计不调优 V1，
而是验证更符合产业行情的离散路径：静默积累 -> 市场确认 -> 过热。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd
import tushare as ts

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


EXPERIMENT_ID = "sector_takeoff_path_state_audit_v2"
REPORT_PATH = Path("docs/research/sector-takeoff-path-state-audit-v2.md")
AS_OF_DATE = "20260728"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="板块起飞证据状态转移审计 V2",
    category="failure_attribution_audit",
    hypothesis=(
        "板块大行情前的价格资金证据不是单调高分，而是静默积累、市场确认、"
        "过热三种状态之间的离散转移"
    ),
    definition={
        "source_experiment": "sector_takeoff_evidence_v1",
        "source_table": "monthly_sector_samples",
        "strict_takeoff_label": "future_ret_60>=30% and future_excess_60>=20%",
        "states": {
            "quiet_accumulation": {
                "ret_60": [-0.15, 0.15],
                "ret_20_min_exclusive": 0.0,
                "amount_ratio_20_120": [1.05, 2.50],
                "turnover_ratio_20_120": [1.00, 2.50],
                "distance_to_high_120_min": -0.25,
            },
            "confirming": {
                "ret_60": [0.05, 0.35],
                "ret_20_min_exclusive": 0.0,
                "amount_ratio_20_120": [1.10, 2.50],
                "turnover_ratio_20_120": [1.00, 2.50],
                "distance_to_high_120_min": -0.10,
            },
            "overheated": {
                "ret_60_min_exclusive": 0.50,
                "or_ret_120_min_exclusive": 1.00,
            },
        },
        "recent_diffusion_confirmation": {
            "breadth_20_min": 0.55,
            "breadth_acceleration_min": 0.05,
            "auxiliary_only_due_history_start_20241220": True,
        },
        "windows": {
            "calibration": ["20210101", "20231231"],
            "late_validation": ["20240101", "20251231"],
            "current": AS_OF_DATE,
        },
        "path_test": "quiet state followed by confirming state within next 3 monthly observations",
        "interpretation": (
            "exploratory failure attribution; no strategy promotion even if a state passes"
        ),
        "execution": "research_only_no_orders_no_scheduler_no_bark",
        "methodology_version": "v2",
    },
)


def classify_states(samples: pd.DataFrame) -> pd.DataFrame:
    """按冻结阈值分类，所有状态只使用当期和历史字段。"""
    result = samples.copy()
    overheated = result["ret_60"].gt(0.50) | result["ret_120"].gt(1.00)
    confirming = (
        result["ret_60"].between(0.05, 0.35)
        & result["ret_20"].gt(0.0)
        & result["amount_ratio_20_120"].between(1.10, 2.50)
        & result["turnover_ratio_20_120"].between(1.00, 2.50)
        & result["distance_to_high_120"].ge(-0.10)
    )
    quiet = (
        result["ret_60"].between(-0.15, 0.15)
        & result["ret_20"].gt(0.0)
        & result["amount_ratio_20_120"].between(1.05, 2.50)
        & result["turnover_ratio_20_120"].between(1.00, 2.50)
        & result["distance_to_high_120"].ge(-0.25)
    )
    result["state"] = "no_signal"
    result.loc[quiet, "state"] = "quiet_accumulation"
    result.loc[confirming, "state"] = "confirming"
    result.loc[overheated, "state"] = "overheated"
    result["diffusion_confirmed"] = (
        result["breadth_20"].ge(0.55)
        & result["breadth_acceleration"].ge(0.05)
    )
    return result


def evaluate_states(samples: pd.DataFrame) -> pd.DataFrame:
    """比较校准期、后段验证期与全样本的状态结果。"""
    rows: list[dict[str, Any]] = []
    windows = {
        "calibration_2021_2023": ("20210101", "20231231"),
        "late_validation_2024_2025": ("20240101", "20251231"),
        "all_2021_2025": ("20210101", "20251231"),
    }
    for window, (start, end) in windows.items():
        frame = samples[
            samples["trade_date"].between(start, end)
        ].dropna(subset=["future_ret_60", "future_excess_60"])
        baseline = float(frame["strict_takeoff"].mean())
        for state in [
            "quiet_accumulation",
            "confirming",
            "overheated",
            "no_signal",
        ]:
            group = frame[frame["state"].eq(state)]
            hit_rate = float(group["strict_takeoff"].mean()) if len(group) else 0.0
            rows.append(
                {
                    "window": window,
                    "state": state,
                    "samples": int(len(group)),
                    "baseline_hit_rate": baseline,
                    "strict_hit_rate": hit_rate,
                    "hit_lift": hit_rate / baseline if baseline > 0 else 0.0,
                    "mean_future_return": (
                        float(group["future_ret_60"].mean()) if len(group) else 0.0
                    ),
                    "mean_future_excess": (
                        float(group["future_excess_60"].mean()) if len(group) else 0.0
                    ),
                }
            )
    return pd.DataFrame(rows)


def evaluate_transitions(samples: pd.DataFrame) -> dict[str, Any]:
    """检验静默积累后 3 个月内进入确认状态的频率与后续结果。"""
    ordered = samples.sort_values(["ts_code", "trade_date"]).copy()
    grouped = ordered.groupby("ts_code", sort=False)["state"]
    next_states = pd.concat(
        [grouped.shift(-offset).rename(f"state_plus_{offset}") for offset in [1, 2, 3]],
        axis=1,
    )
    ordered = pd.concat([ordered, next_states], axis=1)
    ordered["quiet_to_confirming_3m"] = (
        ordered["state"].eq("quiet_accumulation")
        & next_states.eq("confirming").any(axis=1)
    )
    frame = ordered[
        ordered["trade_date"].between("20210101", "20251231")
    ].dropna(subset=["future_ret_60", "future_excess_60"])
    quiet = frame[frame["state"].eq("quiet_accumulation")]
    transition = frame[frame["quiet_to_confirming_3m"]]
    return {
        "quiet_samples": int(len(quiet)),
        "transition_samples": int(len(transition)),
        "transition_share_of_quiet": (
            float(len(transition) / len(quiet)) if len(quiet) else 0.0
        ),
        "quiet_hit_rate": float(quiet["strict_takeoff"].mean()) if len(quiet) else 0.0,
        "transition_hit_rate": (
            float(transition["strict_takeoff"].mean()) if len(transition) else 0.0
        ),
        "transition_mean_future_excess": (
            float(transition["future_excess_60"].mean())
            if len(transition)
            else 0.0
        ),
    }


def current_states(
    samples: pd.DataFrame,
    names: pd.DataFrame,
) -> pd.DataFrame:
    """输出当前静默积累与确认板块，宽度只作辅助排序。"""
    current = samples[samples["trade_date"].eq(AS_OF_DATE)].copy()
    current = current[
        current["state"].isin(["quiet_accumulation", "confirming"])
    ]
    current = current.merge(
        names[["ts_code", "name"]].drop_duplicates("ts_code", keep="last"),
        on="ts_code",
        how="left",
    )
    current["state_priority"] = current["state"].map(
        {"confirming": 2, "quiet_accumulation": 1}
    )
    current["diffusion_priority"] = current["diffusion_confirmed"].astype(int)
    columns = [
        "ts_code",
        "name",
        "state",
        "diffusion_confirmed",
        "ret_20",
        "ret_60",
        "ret_120",
        "amount_ratio_20_120",
        "turnover_ratio_20_120",
        "distance_to_high_120",
        "breadth_20",
        "breadth_acceleration",
        "leading_pct_20",
    ]
    return (
        current.sort_values(
            [
                "state_priority",
                "diffusion_priority",
                "breadth_acceleration",
                "amount_ratio_20_120",
            ],
            ascending=False,
        )[columns]
        .reset_index(drop=True)
    )


def run_audit(
    paths: RuntimePaths,
    source_dataset: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记 V2 后读取 V1 研究库，执行状态归因。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=AS_OF_DATE,
        data_version=f"sector_takeoff_evidence_v1:{source_dataset.stat().st_size}",
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        samples = _load_samples(source_dataset)
        classified = classify_states(samples)
        state_metrics = evaluate_states(classified)
        transitions = evaluate_transitions(classified)
        names = _load_current_names()
        current = current_states(classified, names)
        result = _persist_and_complete(
            paths,
            attempt,
            source_dataset,
            state_metrics,
            transitions,
            current,
        )
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _persist_and_complete(
    paths: RuntimePaths,
    attempt: ResearchAttempt,
    source_dataset: Path,
    state_metrics: pd.DataFrame,
    transitions: dict[str, Any],
    current: pd.DataFrame,
) -> dict[str, Any]:
    state_path = attempt.output_dir / "state_validation.csv"
    current_path = attempt.output_dir / "current_state_candidates.csv"
    state_metrics.to_csv(state_path, index=False)
    current.to_csv(current_path, index=False)
    late = state_metrics[
        state_metrics["window"].eq("late_validation_2024_2025")
    ]
    late_records = _records(late)
    metrics = {
        "source_dataset": str(source_dataset),
        "late_validation": late_records,
        "transitions": transitions,
        "current_candidate_count": int(len(current)),
        "current_confirming_count": int(current["state"].eq("confirming").sum()),
        "current_quiet_count": int(
            current["state"].eq("quiet_accumulation").sum()
        ),
        "current_diffusion_confirmed_count": int(
            current["diffusion_confirmed"].sum()
        ),
        "current_top_candidates": _records(current.head(30)),
        "passed_as_strategy": False,
        "decision": "RESEARCH_PATH_ONLY",
    }
    report = render_report(metrics, state_metrics)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report, encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=metrics,
        outcome="RESEARCH_PATH_ONLY",
        decision_reason=(
            "状态转移用于解释和候选分层；V1 单调分数已失败，V2 不升级交易策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "状态转移审计摘要"),
            ExperimentArtifact("report", report_path, "状态转移审计报告"),
            ExperimentArtifact("state_validation", state_path, "状态分段验证"),
            ExperimentArtifact(
                "current_candidates",
                current_path,
                "当前状态候选",
            ),
        ],
    )
    return {**metrics, "reused": False}


def render_report(
    metrics: dict[str, Any],
    state_metrics: pd.DataFrame,
) -> str:
    state_rows = "\n".join(
        f"| {row['window']} | {row['state']} | {row['samples']} | "
        f"{row['baseline_hit_rate']:.2%} | {row['strict_hit_rate']:.2%} | "
        f"{row['hit_lift']:.2f} | {row['mean_future_excess']:.2%} |"
        for row in state_metrics.to_dict("records")
    )
    candidate_rows = "\n".join(
        f"| {index + 1} | {row.get('name') or '-'} | {row['ts_code']} | "
        f"{row['state']} | {'是' if row['diffusion_confirmed'] else '否'} | "
        f"{row['ret_60']:.2%} | {row['amount_ratio_20_120']:.2f} | "
        f"{row['breadth_20']:.1%} |"
        for index, row in enumerate(metrics["current_top_candidates"])
    )
    transition = metrics["transitions"]
    return f"""# 板块起飞证据状态转移审计 V2

V1 已经否决“证据分越高，未来起飞概率越高”。本审计不修改 V1，
而是把板块放进三种可解释状态：静默积累、市场确认、过热。

## 状态定义

- 静默积累：60 日收益 -15%~15%，20 日转正，成交额扩张 1.05~2.5 倍，
  换手扩张 1~2.5 倍，距离 120 日高点不低于 -25%。
- 市场确认：60 日收益 5%~35%，20 日转正，成交额扩张至少 1.1 倍，
  换手扩张至少 1 倍，距离 120 日高点不低于 -10%。
- 过热：60 日涨幅超过 50% 或 120 日涨幅超过 100%。
- 近期扩散确认：20 日上涨宽度至少 55%，且较 60 日宽度提高至少 5 个百分点。
  宽度只从 2024-12-20 可用，因此不进入长期状态定义。

## 分段结果

| 窗口 | 状态 | 样本 | 全体起飞率 | 状态起飞率 | 提升倍数 | 未来平均超额 |
|---|---|---:|---:|---:|---:|---:|
{state_rows}

## 路径检验

- 静默积累样本：{transition['quiet_samples']:,}。
- 3 个月内进入确认：{transition['transition_samples']:,}
  （{transition['transition_share_of_quiet']:.2%}）。
- 静默积累本身起飞率：{transition['quiet_hit_rate']:.2%}。
- 后续进入确认的静默积累起飞率：{transition['transition_hit_rate']:.2%}。
- 上述转移样本未来 60 日平均超额：{transition['transition_mean_future_excess']:.2%}。

注意：是否在未来进入确认是事后路径描述，不能在静默积累当日作为交易信号。

## 当前状态候选（未做主题去重）

| 排名 | 板块 | 代码 | 状态 | 扩散确认 | 60日收益 | 成交额扩张 | 20日宽度 |
|---:|---|---|---|---|---:|---:|---:|
{candidate_rows}

## 结论边界

- V2 是 V1 失败后的机制归因，不是新策略优化。
- 当前榜单仍包含大量同义、重叠概念，必须按成分重叠聚类后才能形成方向级结论。
- 价格资金状态只能说明市场识别阶段；产业催化与财务兑现必须用公告时点单独确认。
"""


def _load_samples(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    with duckdb.connect(str(path), read_only=True) as con:
        return con.execute(
            "SELECT * FROM monthly_sector_samples ORDER BY ts_code, trade_date"
        ).fetchdf()


def _load_current_names() -> pd.DataFrame:
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN")
    frame = ts.pro_api(token).dc_index(trade_date=AS_OF_DATE)
    if frame.empty:
        raise RuntimeError("当前 DC 板块列表为空")
    return frame


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run_audit(
        get_runtime_paths(),
        args.source_dataset,
        force=args.force,
    )
    print(
        {
            "decision": result.get("decision"),
            "transitions": result.get("transitions"),
            "current_confirming_count": result.get("current_confirming_count"),
            "current_quiet_count": result.get("current_quiet_count"),
            "current_diffusion_confirmed_count": result.get(
                "current_diffusion_confirmed_count"
            ),
            "current_top_candidates": result.get(
                "current_top_candidates",
                [],
            )[:15],
            "reused": result.get("reused"),
        }
    )


if __name__ == "__main__":
    main()
