"""跨因子研究的验证窗口偏差与样本外衰减审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

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
    research_fingerprint,
)
from examples.factor_research_meta_report import render_report


EXPERIMENT_ID = "factor_research_meta_audit_v1"
REPORT_PATH = Path("docs/research/factor-research-meta-audit-v1.md")
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="跨因子研究稳健性元审计 V1",
    category="research_governance",
    hypothesis="单一2019至2021验证窗口是否系统性高估候选因子有效性",
    definition={
        "input": "experiment_repository_latest_success_runs",
        "inclusion": {
            "experiment_category": "factor_strategy",
            "experiment_status": "exclude_needs_revalidation",
            "required_periods": ["validation", "locked_test", "full"],
            "required_artifacts": ["annual_metrics", "strategy_id"],
            "same_family_rule": "strip_trailing_version_then_keep_latest_run",
        },
        "diagnostics": [
            "validation_to_locked_return_decay",
            "validation_to_locked_sharpe_decay",
            "core_gate_false_discovery_rate",
            "validation_locked_spearman",
            "top_quartile_persistence",
            "annual_positive_breadth",
            "quality_correlation_distribution",
        ],
        "core_gate": {
            "annual_return_min": 0.08,
            "sharpe_min": 0.55,
            "max_drawdown_floor": -0.30,
            "positive_excess": True,
        },
        "quality_balanced_value": "multi_fold_process_comparator_only",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """绑定源实验指纹后执行元分析。"""
    manifest = load_source_manifest(paths)
    data_version = research_fingerprint({"source_runs": manifest})
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=data_version,
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


def load_source_manifest(paths: RuntimePaths) -> list[dict[str, str]]:
    """只读取源运行身份，作为稳定数据版本，不加载大体量结果。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT
                    r.*,
                    e.category,
                    e.status AS experiment_status,
                    e.definition_fingerprint AS current_definition_fingerprint,
                    r.definition_fingerprint AS run_definition_fingerprint,
                    ROW_NUMBER() OVER(
                        PARTITION BY r.experiment_id
                        ORDER BY r.created_at DESC
                    ) AS rn
                FROM experiment_runs r
                JOIN experiments e USING(experiment_id)
                WHERE r.status = 'SUCCESS'
                  AND e.category = 'factor_strategy'
            )
            SELECT experiment_id, run_id, run_fingerprint, outcome
                 , experiment_status, current_definition_fingerprint
                 , run_definition_fingerprint
            FROM ranked
            WHERE rn = 1
            ORDER BY experiment_id
            """
        ).fetchall()
    return [
        {
            "experiment_id": str(row["experiment_id"]),
            "run_id": str(row["run_id"]),
            "run_fingerprint": str(row["run_fingerprint"]),
            "outcome": str(row["outcome"]),
            "experiment_status": str(row["experiment_status"]),
            "current_definition_fingerprint": str(
                row["current_definition_fingerprint"]
            ),
            "run_definition_fingerprint": str(row["run_definition_fingerprint"]),
        }
        for row in rows
    ]


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """读取统一实验指标并量化验证到锁定期的衰减。"""
    pending = load_pending_revalidations(paths)
    runs = select_current_runs(load_eligible_runs(paths))
    if len(runs) < 5:
        raise ValueError("可比的独立因子实验不足5个，不能执行元分析")
    rows = build_comparison_rows(runs)
    summary = summarize_decay(rows)
    annual_breadth = build_annual_breadth(runs)
    comparator = load_multifold_comparator(paths)
    report_path = paths.root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(
            rows,
            summary,
            annual_breadth,
            comparator,
            pending,
            as_of_date,
        ),
        encoding="utf-8",
    )
    decision = (
        "REVALIDATION_BLOCKED"
        if pending
        else "REQUIRE_MULTI_FOLD_FOR_NEW_FACTOR_RESEARCH"
    )
    return {
        "as_of_date": as_of_date,
        "included_experiments": len(rows),
        "pending_revalidation_count": len(pending),
        "pending_revalidations": pending,
        "summary": summary,
        "experiment_rows": rows,
        "annual_breadth": annual_breadth,
        "multifold_comparator": comparator,
        "evidence_gap": (
            "历史实验未统一保存逐期市值和行业暴露，不能据此证明共同衰减来自小盘或行业集中"
        ),
        "decision": decision,
        "report_path": str(report_path),
        "reused": False,
    }


def load_eligible_runs(paths: RuntimePaths) -> list[dict[str, Any]]:
    """加载具备直接三段指标和年度明细的最新独立因子运行。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT
                    r.*,
                    e.name,
                    e.category,
                    e.status AS experiment_status,
                    e.definition_fingerprint AS current_definition_fingerprint,
                    ROW_NUMBER() OVER(
                        PARTITION BY r.experiment_id
                        ORDER BY r.created_at DESC
                    ) AS rn
                FROM experiment_runs r
                JOIN experiments e USING(experiment_id)
                WHERE r.status = 'SUCCESS'
                  AND e.category = 'factor_strategy'
            )
            SELECT experiment_id, name, run_id, created_at, metrics_json,
                   experiment_status, current_definition_fingerprint,
                   definition_fingerprint AS run_definition_fingerprint
            FROM ranked
            WHERE rn = 1
            ORDER BY created_at
            """
        ).fetchall()
    eligible: list[dict[str, Any]] = []
    for row in rows:
        metrics = json.loads(str(row["metrics_json"] or "{}"))
        periods = metrics.get("period_metrics")
        required = {"validation", "locked_test", "full"}
        if (
            not isinstance(periods, dict)
            or not required.issubset(periods)
            or not isinstance(metrics.get("annual_metrics"), dict)
            or not metrics.get("strategy_id")
        ):
            continue
        eligible.append(
            {
                "experiment_id": str(row["experiment_id"]),
                "name": str(row["name"]),
                "run_id": str(row["run_id"]),
                "created_at": str(row["created_at"]),
                "experiment_status": str(row["experiment_status"]),
                "current_definition_fingerprint": str(
                    row["current_definition_fingerprint"]
                ),
                "run_definition_fingerprint": str(
                    row["run_definition_fingerprint"]
                ),
                "metrics": metrics,
            }
        )
    return eligible


def load_pending_revalidations(paths: RuntimePaths) -> list[dict[str, str]]:
    """列出风险口径已变更但尚未完成独立复验的因子实验。"""
    return [
        {
            "experiment_id": item["experiment_id"],
            "run_id": item["run_id"],
            "outcome": item["outcome"],
        }
        for item in load_source_manifest(paths)
        if item["experiment_status"] == "needs_revalidation"
    ]


def collapse_version_families(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一研究家族只保留创建时间最新的版本。"""
    latest: dict[str, dict[str, Any]] = {}
    for run in sorted(runs, key=lambda item: item["created_at"]):
        family = re.sub(r"_v\d+$", "", str(run["experiment_id"]))
        latest[family] = {**run, "family": family}
    return sorted(latest.values(), key=lambda item: item["experiment_id"])


def select_current_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """先锁定家族最新版，再排除待复验或定义指纹不一致的结果。"""
    latest = collapse_version_families(runs)
    return [
        run
        for run in latest
        if run["experiment_status"] != "needs_revalidation"
        and run["current_definition_fingerprint"]
        == run["run_definition_fingerprint"]
    ]


def build_comparison_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """展开验证期、锁定期和全样本指标。"""
    rows: list[dict[str, Any]] = []
    for run in runs:
        periods = run["metrics"]["period_metrics"]
        validation = periods["validation"]
        locked = periods["locked_test"]
        full = periods["full"]
        validation_pass = _core_gate_pass(validation)
        locked_pass = _core_gate_pass(locked)
        rows.append(
            {
                "experiment_id": run["experiment_id"],
                "name": run["name"],
                "family": run["family"],
                "validation_return": float(validation["annualized_return"]),
                "locked_return": float(locked["annualized_return"]),
                "return_decay": float(
                    locked["annualized_return"] - validation["annualized_return"]
                ),
                "validation_sharpe": float(validation["sharpe"]),
                "locked_sharpe": float(locked["sharpe"]),
                "sharpe_decay": float(locked["sharpe"] - validation["sharpe"]),
                "validation_drawdown": float(validation["max_drawdown"]),
                "locked_drawdown": float(locked["max_drawdown"]),
                "locked_excess": float(locked["excess_return"]),
                "full_turnover": float(full["annual_turnover"]),
                "quality_correlation": _optional_float(
                    run["metrics"].get("quality_return_correlation")
                ),
                "validation_core_pass": validation_pass,
                "locked_core_pass": locked_pass,
            }
        )
    return rows


def summarize_decay(rows: list[dict[str, Any]]) -> dict[str, float]:
    """汇总验证期乐观偏差和排名稳定性。"""
    frame = pd.DataFrame(rows)
    promising = frame[frame["validation_core_pass"]]
    false_discoveries = promising[~promising["locked_core_pass"]]
    validation_top = frame[
        frame["validation_sharpe"].ge(frame["validation_sharpe"].quantile(0.75))
    ]
    locked_threshold = frame["locked_sharpe"].quantile(0.75)
    quality = pd.to_numeric(frame["quality_correlation"], errors="coerce").dropna()
    return {
        "experiment_count": float(len(frame)),
        "median_validation_return": float(frame["validation_return"].median()),
        "median_locked_return": float(frame["locked_return"].median()),
        "median_return_decay": float(frame["return_decay"].median()),
        "median_validation_sharpe": float(frame["validation_sharpe"].median()),
        "median_locked_sharpe": float(frame["locked_sharpe"].median()),
        "median_sharpe_decay": float(frame["sharpe_decay"].median()),
        "validation_positive_ratio": float(frame["validation_return"].gt(0).mean()),
        "locked_positive_ratio": float(frame["locked_return"].gt(0).mean()),
        "validation_core_pass_count": float(len(promising)),
        "locked_core_pass_count": float(frame["locked_core_pass"].sum()),
        "validation_false_discovery_ratio": (
            float(len(false_discoveries) / len(promising))
            if len(promising)
            else float("nan")
        ),
        "return_rank_spearman": float(
            frame["validation_return"].corr(frame["locked_return"], method="spearman")
        ),
        "sharpe_rank_spearman": float(
            frame["validation_sharpe"].corr(frame["locked_sharpe"], method="spearman")
        ),
        "validation_top_quartile_locked_persistence": float(
            validation_top["locked_sharpe"].ge(locked_threshold).mean()
        ),
        "median_full_turnover": float(frame["full_turnover"].median()),
        "median_quality_correlation": (
            float(quality.median()) if not quality.empty else float("nan")
        ),
    }


def build_annual_breadth(runs: list[dict[str, Any]]) -> list[dict[str, float]]:
    """按年统计候选收益中位数和正收益广度。"""
    by_year: dict[str, list[float]] = {}
    for run in runs:
        for year, metrics in run["metrics"]["annual_metrics"].items():
            value = metrics.get("annualized_return")
            if value is not None:
                by_year.setdefault(str(year), []).append(float(value))
    return [
        {
            "year": float(year),
            "experiment_count": float(len(values)),
            "median_return": float(pd.Series(values).median()),
            "positive_ratio": float(pd.Series(values).gt(0).mean()),
        }
        for year, values in sorted(by_year.items())
        if len(values) >= 5
    ]


def load_multifold_comparator(paths: RuntimePaths) -> dict[str, Any]:
    """读取已经通过多折门槛的 Quality Balanced Value 作为流程对照。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        row = connection.execute(
            """
            SELECT metrics_json
            FROM experiment_runs
            WHERE experiment_id = 'quality_balanced_value_forward_paper_v1'
              AND status = 'SUCCESS'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return {}
    metrics = json.loads(str(row[0] or "{}"))
    return {
        "strategy_id": metrics.get("strategy_id"),
        "period_metrics": metrics.get("period_metrics", {}),
        "gate": metrics.get("gate", {}),
    }


def _core_gate_pass(metrics: dict[str, Any]) -> bool:
    return bool(
        float(metrics["annualized_return"]) >= 0.08
        and float(metrics["sharpe"]) >= 0.55
        and float(metrics["max_drawdown"]) >= -0.30
        and float(metrics["excess_return"]) > 0
    )


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """保存元分析报告和结构化实验对比表。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    table_path = attempt.output_dir / "experiment_decay.csv"
    pd.DataFrame(result["experiment_rows"]).to_csv(table_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=(
            "INCOMPLETE"
            if result["decision"] == "REVALIDATION_BLOCKED"
            else "COMPLETED"
        ),
        decision_reason=(
            f"仍有{result['pending_revalidation_count']}项风险口径待复验，"
            "当前元分析仅作方向性参考"
            if result["decision"] == "REVALIDATION_BLOCKED"
            else "单一验证窗口存在系统性乐观偏差，后续新因子必须使用多折验证"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "跨实验元分析"),
            ExperimentArtifact("comparison", table_path, "实验衰减对比"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
