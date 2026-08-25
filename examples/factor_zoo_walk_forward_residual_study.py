"""因子动物园中盘风格残差的固定走步元研究。"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fund_portfolio import load_fund_portfolio_panel
from examples.factor_research_meta_audit import (
    load_eligible_runs,
    load_source_manifest,
    select_current_runs,
)
from examples.factor_zoo_common_mode_metrics import (
    build_annual_metric_matrix,
)
from examples.factor_zoo_walk_forward_residual_metrics import (
    LOCKED_TRAIN_YEARS,
    LOCKED_YEARS,
    VALIDATION_TRAIN_YEARS,
    VALIDATION_YEARS,
    evaluate_residual_candidates,
    summarize_candidate_rows,
)
from examples.factor_zoo_walk_forward_residual_report import render_report
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


EXPERIMENT_ID = "factor_zoo_walk_forward_midcap_residual_v1"
REPORT_PATH = Path(
    "docs/research/factor-zoo-walk-forward-midcap-residual-v1.md"
)
ASSETS = ["510300.SH", "510500.SH"]
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="因子动物园走步中盘残差 V1",
    category="research_governance",
    hypothesis="剔除训练期估计的中盘风格后，旧因子是否仍有跨窗口独立残差",
    definition={
        "factor_source": (
            "experiment_repository_latest_valid_factor_families"
        ),
        "style": "510500_annual_return_minus_510300_annual_return",
        "walk_forward": {
            "validation_train": VALIDATION_TRAIN_YEARS,
            "validation_apply": VALIDATION_YEARS,
            "locked_train": LOCKED_TRAIN_YEARS,
            "locked_apply": LOCKED_YEARS,
            "regression": "ols_with_intercept_estimate_beta_only",
            "residual": "annual_excess_minus_frozen_beta_times_style",
        },
        "frozen_gate": {
            "validation_mean_residual_positive": True,
            "locked_mean_residual_positive": True,
            "locked_positive_year_share_min": 0.60,
            "locked_residual_information_ratio_min": 0.25,
            "locked_worst_residual_floor": -0.20,
        },
        "interpretation": (
            "historical_meta_diagnostic_only_not_promotion_evidence"
        ),
        "no_strategy_or_production_change": True,
        "methodology_version": "two_stage_walk_forward_annual_v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """绑定旧实验和ETF文件版本后执行走步残差诊断。"""
    data_version = research_fingerprint(
        {
            "source_runs": load_source_manifest(paths),
            "style_files": _style_file_versions(paths),
        }
    )
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
    except BaseException as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """构造完整年度面板并评价全部旧因子残差。"""
    runs = select_current_runs(load_eligible_runs(paths))
    years = sorted(
        set(
            VALIDATION_TRAIN_YEARS
            + VALIDATION_YEARS
            + LOCKED_YEARS
        )
    )
    excess_matrix, excluded = build_annual_metric_matrix(
        runs,
        metric_name="excess_return",
        years=years,
    )
    midcap_spread = _load_midcap_spread(paths, as_of_date, years)
    rows = evaluate_residual_candidates(
        excess_matrix,
        midcap_spread,
    )
    summary = summarize_candidate_rows(rows)
    decision = (
        "EXISTING_FACTOR_RESIDUAL_CANDIDATE_FOUND"
        if summary["gate_pass_count"] > 0
        else "NO_EXISTING_FACTOR_PASSES_STYLE_RESIDUAL_GATE"
    )
    result = {
        "as_of_date": str(as_of_date),
        "included_candidate_count": len(rows),
        "excluded_experiments": excluded,
        "summary": summary,
        "candidate_rows": rows,
        "decision": decision,
        "explanation": (
            "至少一个旧因子通过历史残差诊断，但仍只能另行冻结前瞻Paper。"
            if summary["gate_pass_count"] > 0
            else "旧因子的正收益大多无法在剔除中盘风格后跨验证与锁定窗口稳定保留。"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result


def _load_midcap_spread(
    paths: RuntimePaths,
    as_of_date: str,
    years: list[int],
) -> pd.Series:
    """从统一qfq基金面板读取年度中盘相对大盘收益。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        ASSETS,
        start_date="20140101",
        end_date=as_of_date,
    )
    annual = panel.adjusted_close.groupby(
        panel.adjusted_close.index.year
    ).apply(lambda frame: frame.iloc[-1] / frame.iloc[0] - 1.0)
    spread = annual["510500.SH"] - annual["510300.SH"]
    return spread.reindex(years)


def _style_file_versions(paths: RuntimePaths) -> list[str]:
    """把历史基金库和增量基准库纳入运行指纹。"""
    versions: list[str] = []
    for path in [
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
    ]:
        stat = path.stat()
        versions.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    return versions


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """保存候选残差明细和报告，不改变实验策略状态。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rows_path = attempt.output_dir / "candidate_residuals.csv"
    flat_rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"validation_residuals", "locked_residuals"}
        }
        for row in result["candidate_rows"]
    ]
    pd.DataFrame(flat_rows).to_csv(rows_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            "因子动物园走步中盘残差诊断完成："
            f"{result['decision']}"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "走步残差报告"),
            ExperimentArtifact(
                "candidate_residuals",
                rows_path,
                "候选样本外残差",
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
