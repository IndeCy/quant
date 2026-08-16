"""净派息收益率组合的历史依赖门禁审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


EXPERIMENT_ID = "net_payout_yield_dependency_feasibility_v1"
REPORT_PATH = Path("docs/research/net-payout-yield-dependency-feasibility-v1.md")
DEPENDENCIES = (
    "dividend_growth_persistence_v3",
    "net_share_issuance_investable_adjustment_feasibility_v2",
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="净派息收益率组合依赖可行性 V1",
    category="data_feasibility",
    hypothesis="现金分红减股本扩张能否由已验证因子资产可信组合",
    definition={
        "factor_combination": {
            "positive_component": "implemented_cash_dividend",
            "negative_component": "annual_total_share_growth",
            "direction": "higher_is_better",
        },
        "dependencies": list(DEPENDENCIES),
        "gate": "all_dependencies_must_have_passed_latest_outcome",
        "decision": "no_data_scan_or_backtest_when_dependency_failed",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记组合指纹并读取实验仓库，不触碰原始大表。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version="experiment_repository_dependencies_v1",
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        repository = SystemRepository(paths.system_state_path)
        dependencies = {
            experiment_id: _latest_outcome(repository, experiment_id)
            for experiment_id in DEPENDENCIES
        }
        passed = all(
            item["status"] == "SUCCESS"
            and str(item["outcome"]).startswith("PASSED")
            for item in dependencies.values()
        )
        result = {
            "dependencies": dependencies,
            "passed": passed,
            "decision": (
                "ELIGIBLE_FOR_FACTOR_DESIGN"
                if passed
                else "REJECTED_BEFORE_DATA_SCAN"
            ),
            "reused": False,
        }
        report_path = paths.root / REPORT_PATH
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(result), encoding="utf-8")
        result["report_path"] = str(report_path)
        _complete(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _latest_outcome(
    repository: SystemRepository,
    experiment_id: str,
) -> dict[str, str]:
    """读取依赖实验最新运行结论。"""
    detail = repository.load_experiment_detail(experiment_id)
    latest = detail.get("latest_run") if detail else None
    return {
        "status": str(latest.get("status", "")) if latest else "MISSING",
        "outcome": str(latest.get("outcome", "")) if latest else "",
        "decision_reason": (
            str(latest.get("decision_reason", "")) if latest else "实验不存在"
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    """生成依赖门禁报告。"""
    rows = "\n".join(
        f"| {experiment_id} | {item['status']} | {item['outcome']} | "
        f"{item['decision_reason']} |"
        for experiment_id, item in result["dependencies"].items()
    )
    return f"""# 净派息收益率组合依赖可行性 V1

| 依赖实验 | 状态 | 结论 | 原因 |
|---|---|---|---|
{rows}

## 结论

- 决策：`{result['decision']}`。
- 组合依赖未全部通过时，不扫描数据、不回测，也不通过改名绕过失败指纹。
"""


def _complete(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """把未启动原因写入统一实验仓库。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if result["passed"] else "REJECTED",
        decision_reason=(
            "净派息组合依赖均通过，可另行冻结因子"
            if result["passed"]
            else "分红增长或净股本发行已有终止结论，组合不进入数据扫描"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "组合依赖门禁报告")
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
