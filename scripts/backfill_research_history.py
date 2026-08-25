"""把去重门禁上线前的研究结果补入统一实验资产库。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.quality_lowbeta_study import RESEARCH_SPEC as LOWBETA_SPEC
from examples.quality_ml_ranker_v0 import RESEARCH_SPEC as ML_SPEC
from examples.quality_value_lowvol_risk_recovery_study import (
    RESEARCH_SPEC as RECOVERY_SPEC,
)
from runtime.experiment_runner import ExperimentArtifact
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_attempts import (
    ResearchSpec,
    begin_research_attempt,
    build_run_fingerprint,
    complete_research_attempt,
    research_fingerprint,
)


HISTORY_AS_OF = "20260722"
FACTOR_SPEC = ResearchSpec(
    experiment_id="quality_value_lowvol_factor_v0",
    name="Quality Value LowVol Factor V0",
    category="factor_strategy",
    hypothesis="质量、价值和低波组合能否形成可执行的防御型因子资产",
    lifecycle_status="retired",
    definition={
        "factors": {
            "roa": 0.20,
            "ocf_to_or": 0.20,
            "earnings_yield": 0.20,
            "book_yield": 0.20,
            "low_volatility_60d": 0.20,
        },
        "transform": "winsorize_1_99_then_zscore",
        "universe": "quality_cleanup_with_corporate_action_gate_10pct",
        "portfolio": {"top_n": 20, "weight": "equal", "rebalance": "monthly"},
        "risk_overlay": {"window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "execution": {"model": "M0", "lag": 1, "adjust": "qfq", "slippage_bps": 5.0},
        "methodology_version": "v0",
    },
)


def backfill_research_history(paths: RuntimePaths) -> dict[str, str]:
    """幂等补录三份 Markdown 研究和已有 ML 运行。"""
    results = {
        "quality_ml_ranker_v0": _annotate_ml_history(paths),
        "quality_value_lowvol_factor_v0": _register_markdown_attempt(
            paths,
            FACTOR_SPEC,
            "docs/research/quality-value-lowvol-factor-study.md",
            {
                "summary": {
                    "annualized_return": 0.1148,
                    "max_drawdown": -0.3126,
                    "sharpe": 0.635,
                    "total_return": 2.3540,
                    "excess_return": 1.7738,
                },
                "gate": {"status": "RETIRED"},
            },
            "RETIRED",
            "公司行动门禁后风险收益退化，后续风险恢复实验未通过，停止生产晋级",
        ),
        "quality_value_lowvol_risk_recovery_v0": _register_markdown_attempt(
            paths,
            RECOVERY_SPEC,
            "docs/research/quality-value-lowvol-risk-recovery-study.md",
            {
                "baseline": {
                    "annualized_return": 0.1148,
                    "max_drawdown": -0.3126,
                    "sharpe": 0.635,
                    "calmar": 0.367,
                    "total_return": 2.3540,
                    "execution_cost": 239115.12,
                },
                "recovery": {
                    "annualized_return": 0.0953,
                    "max_drawdown": -0.3571,
                    "sharpe": 0.585,
                    "calmar": 0.267,
                    "total_return": 1.7542,
                    "execution_cost": 177700.32,
                },
                "gate": {
                    "passed": False,
                    "status": "FAIL",
                    "checks": {
                        "annualized_return_at_least_10pct": False,
                        "max_drawdown_within_25pct": False,
                        "calmar_at_least_045": False,
                        "execution_cost_not_worse_10pct": True,
                    },
                },
            },
            "REJECTED",
            "分级恢复降低了收益且未满足回撤和Calmar门槛，终止晋级",
        ),
        "quality_lowbeta_v0": _register_markdown_attempt(
            paths,
            LOWBETA_SPEC,
            "docs/research/quality-lowbeta-study.md",
            {
                "summary": {
                    "annualized_return": 0.0274,
                    "max_drawdown": -0.3882,
                    "sharpe": 0.245,
                    "calmar": 0.071,
                    "total_return": 0.3516,
                    "excess_return": -0.2287,
                    "annual_turnover": 7.7471,
                },
                "gate": {
                    "passed": False,
                    "status": "FAIL",
                    "checks": {
                        "annualized_return_at_least_10pct": False,
                        "max_drawdown_within_25pct": False,
                        "sharpe_at_least_065": False,
                        "calmar_at_least_045": False,
                        "positive_excess_return": False,
                    },
                },
            },
            "REJECTED",
            "固定晋级门槛全部未通过，不注册生产策略",
        ),
    }
    return results


def _annotate_ml_history(paths: RuntimePaths) -> str:
    repository = SystemRepository(paths.system_state_path)
    detail = repository.load_experiment_detail(ML_SPEC.experiment_id)
    if detail is None:
        return "missing"
    definition_fingerprint = research_fingerprint(ML_SPEC.definition)
    repository.upsert_experiment(
        {
            "experiment_id": ML_SPEC.experiment_id,
            "name": ML_SPEC.name,
            "category": ML_SPEC.category,
            "status": ML_SPEC.lifecycle_status,
            "owner": ML_SPEC.owner,
            "description": ML_SPEC.hypothesis,
            "hypothesis": ML_SPEC.hypothesis,
            "definition_fingerprint": definition_fingerprint,
            "config": {"definition": ML_SPEC.definition},
        }
    )
    runs = [run for run in detail["runs"] if run["status"] == "SUCCESS"]
    for index, run in enumerate(reversed(runs)):
        config = dict(run.get("config") or {})
        data_as_of = str(config.get("as_of_date") or "")
        if not data_as_of:
            continue
        gate = dict((run.get("metrics") or {}).get("gate") or {})
        duplicate_note = "；该次为去重门禁上线前的重复计算" if index > 0 else ""
        repository.annotate_experiment_run(
            str(run["run_id"]),
            definition_fingerprint=definition_fingerprint,
            run_fingerprint=build_run_fingerprint(definition_fingerprint, data_as_of),
            data_as_of=data_as_of,
            outcome="PASSED" if gate.get("status") == "PASS" else "REJECTED",
            decision_reason=f"固定样本外晋级门槛未通过{duplicate_note}",
        )
    return f"annotated:{len(runs)}"


def _register_markdown_attempt(
    paths: RuntimePaths,
    spec: ResearchSpec,
    report_relative_path: str,
    metrics: dict[str, Any],
    outcome: str,
    decision_reason: str,
) -> str:
    attempt = begin_research_attempt(
        spec,
        paths=paths,
        data_as_of=HISTORY_AS_OF,
    )
    if not attempt.should_run:
        return f"reused:{attempt.reused_run['run_id']}"
    source = paths.root / report_relative_path
    if not source.exists():
        raise FileNotFoundError(source)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    result = complete_research_attempt(
        attempt,
        metrics={**metrics, "report_path": str(source)},
        outcome=outcome,
        decision_reason=decision_reason,
        artifacts=[ExperimentArtifact("summary", summary_path, "研究报告")],
    )
    return f"registered:{result['run_id']}"


def main() -> None:
    print(
        json.dumps(
            backfill_research_history(get_runtime_paths()),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
