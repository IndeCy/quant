"""正融资净买入股票占比的月频市场状态可行性审计。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples import margin_flow_data_feasibility_study as source
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchAttempt,
    ResearchSpec,
    begin_research_attempt,
    complete_research_attempt,
    fail_research_attempt,
)


EXPERIMENT_ID = "margin_flow_breadth_regime_data_feasibility_v1"
REPORT_PATH = Path(
    "docs/research/margin-flow-breadth-regime-data-feasibility-v1.md"
)
RELIABLE_AS_OF = "20260723"

RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="融资净买入广度月频状态数据可行性 V1",
    category="data_feasibility",
    hypothesis=(
        "T-1可见的20日融资净买入为正股票占全部有效两融股票的比例，能否形成覆盖完整、"
        "状态分布非退化的月频市场风险偏好指标"
    ),
    definition={
        "dependency": source.EXPERIMENT_ID,
        "source": "immutable_margin_flow_feasibility_monthly_coverage_artifact",
        "indicator": "positive_count/valid_count",
        "signal_frequency": "month_end",
        "visibility": "same_T_minus_1_rule_as_source",
        "outcome_returns_loaded": False,
        "gate": {
            "month_count_min": 130,
            "nonzero_valid_share_min": 1.0,
            "median_valid_count_min": 500,
            "breadth_q90_minus_q10_min": 0.10,
            "unique_values_min": 100,
            "breadth_range": [0.0, 1.0],
        },
        "promotion_scope": "feasibility_only_no_strategy_registration",
        "methodology_version": "margin_positive_breadth_v1",
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
        require_source_passed(paths)
        result, monthly = calculate(paths)
        complete_attempt(attempt, result, monthly)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def calculate(
    paths: RuntimePaths,
) -> tuple[dict[str, Any], pd.DataFrame]:
    monthly = load_source_monthly_artifact(paths)
    monthly["margin_breadth"] = (
        pd.to_numeric(monthly["positive_count"], errors="coerce")
        / pd.to_numeric(monthly["valid_count"], errors="coerce").replace(0, pd.NA)
    )
    valid = monthly.dropna(subset=["margin_breadth"]).copy()
    breadth = valid["margin_breadth"].astype(float)
    q10 = float(breadth.quantile(0.10))
    q90 = float(breadth.quantile(0.90))
    metrics = {
        "month_count": len(monthly),
        "valid_month_count": len(valid),
        "nonzero_valid_share": float(monthly["valid_count"].gt(0).mean()),
        "median_valid_count": float(monthly["valid_count"].median()),
        "breadth_min": float(breadth.min()),
        "breadth_q10": q10,
        "breadth_median": float(breadth.median()),
        "breadth_q90": q90,
        "breadth_max": float(breadth.max()),
        "breadth_q90_minus_q10": q90 - q10,
        "unique_values": int(breadth.nunique()),
        "above_half_share": float(breadth.ge(0.50).mean()),
    }
    checks = {
        "month_count_at_least_130": metrics["month_count"] >= 130,
        "nonzero_valid_share_is_100pct": (
            metrics["nonzero_valid_share"] >= 1.0
        ),
        "median_valid_count_at_least_500": (
            metrics["median_valid_count"] >= 500
        ),
        "breadth_q90_minus_q10_at_least_10pct": (
            metrics["breadth_q90_minus_q10"] >= 0.10
        ),
        "unique_values_at_least_100": metrics["unique_values"] >= 100,
        "breadth_within_zero_one": (
            metrics["breadth_min"] >= 0 and metrics["breadth_max"] <= 1
        ),
    }
    passed = all(checks.values())
    result = {
        "experiment_id": EXPERIMENT_ID,
        "period": [
            str(valid["signal_date"].min()),
            str(valid["signal_date"].max()),
        ],
        "metrics": metrics,
        "gate": {"passed": passed, "checks": checks},
        "decision": (
            "CONTINUE_TO_FIXED_MONTHLY_REGIME_BACKTEST"
            if passed
            else "REJECTED_BEFORE_BACKTEST"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report = Path(result["report_path"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    return result, valid


def load_source_monthly_artifact(paths: RuntimePaths) -> pd.DataFrame:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest:
        raise RuntimeError("融资流数据可行性结果不存在")
    path = resolve_migrated_artifact_path(
        paths,
        Path(str(latest["output_dir"])) / "monthly_coverage.csv",
        source.EXPERIMENT_ID,
    )
    return pd.read_csv(path, dtype={"signal_date": str, "visible_through_date": str})


def resolve_migrated_artifact_path(
    paths: RuntimePaths,
    recorded_path: Path,
    experiment_id: str,
) -> Path:
    """旧机绝对路径只映射到当前项目内同实验、同run目录。"""
    if recorded_path.exists():
        return recorded_path
    run_directory = recorded_path.parent.name
    candidate = (
        paths.root
        / "runs"
        / "experiments"
        / experiment_id
        / run_directory
        / recorded_path.name
    )
    if not candidate.exists():
        raise FileNotFoundError(recorded_path)
    return candidate


def require_source_passed(paths: RuntimePaths) -> None:
    experiment = SystemRepository(paths.system_state_path).load_experiment_detail(
        source.EXPERIMENT_ID
    )
    latest = experiment.get("latest_run") if experiment else None
    if not latest or latest.get("outcome") != "PASSED_FEASIBILITY":
        raise RuntimeError("融资流数据源门禁未通过")


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    monthly: pd.DataFrame,
) -> None:
    summary = attempt.output_dir / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    monthly_path = attempt.output_dir / "monthly_breadth.csv"
    monthly.to_csv(monthly_path, index=False)
    metrics_path = attempt.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "融资净买入广度覆盖与分布通过，可进入一次固定月频状态回测"
            if passed
            else "融资净买入广度覆盖或分布不足，终止于回测前"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "融资广度数据门禁报告"),
            ExperimentArtifact("monthly_breadth", monthly_path, "月频融资广度"),
            ExperimentArtifact("metrics", metrics_path, "数据门禁指标"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    m = result["metrics"]
    checks = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in result["gate"]["checks"].items()
    )
    return f"""# 融资净买入广度月频状态数据可行性 V1

- 区间：{result['period'][0]} 至 {result['period'][1]}
- 月份：{m['month_count']}；有效股票数中位：{m['median_valid_count']:.0f}
- 广度 Min/Q10/Median/Q90/Max：{m['breadth_min']:.2%} /
  {m['breadth_q10']:.2%} / {m['breadth_median']:.2%} /
  {m['breadth_q90']:.2%} / {m['breadth_max']:.2%}
- 广度≥50%月份占比：{m['above_half_share']:.2%}

## 冻结门禁

{checks}

## 结论

`{result['decision']}`。本阶段不读取资产收益、不回测、不注册策略。
"""


def _data_version(paths: RuntimePaths) -> str:
    stat = paths.system_state_path.stat()
    return f"system_state:{stat.st_size}:{stat.st_mtime_ns}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=RELIABLE_AS_OF)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
