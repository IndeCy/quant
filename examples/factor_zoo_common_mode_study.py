"""因子动物园共同风险源和中盘风格暴露元研究。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
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
    build_style_attribution,
    evaluate_common_mode_gate,
    summarize_correlation,
)
from examples.factor_zoo_common_mode_report import render_report
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


EXPERIMENT_ID = "factor_zoo_common_mode_attribution_v1"
REPORT_PATH = Path("docs/research/factor-zoo-common-mode-attribution-v1.md")
START_YEAR = 2015
STYLE_ASSETS = ["510300.SH", "510500.SH", "159915.SZ"]
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="因子动物园共同模式归因 V1",
    category="research_governance",
    hypothesis="大量不同名称的因子策略是否主要共享中盘相对沪深300暴露",
    definition={
        "factor_inputs": {
            "source": "experiment_repository_latest_valid_factor_families",
            "annual_metrics": ["annualized_return", "excess_return"],
            "complete_panel_start_year": START_YEAR,
            "family_deduplication": "strip_trailing_version_keep_latest",
        },
        "style_inputs": {
            "adjust_policy": "qfq",
            "hs300": "510300.SH",
            "csi500": "510500.SH",
            "chinext": "159915.SZ",
            "annual_spreads": [
                "csi500_minus_hs300",
                "chinext_minus_hs300",
            ],
        },
        "diagnostics": [
            "pairwise_correlation",
            "principal_component_share",
            "effective_breadth",
            "common_excess_style_regression",
            "midcap_residualized_breadth",
            "yearly_sign_synchronization",
        ],
        "frozen_gate": {
            "excess_pc1_share_min": 0.50,
            "common_midcap_r_squared_min": 0.60,
            "leave_one_year_out_midcap_r_squared_min": 0.60,
            "strategy_midcap_corr_ge_070_share_min": 0.70,
            "effective_breadth_max": 5.0,
        },
        "no_strategy_or_production_change": True,
        "methodology_version": "annual_complete_panel_leave_one_out_v1_1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记实验与ETF数据指纹后执行共同模式审计。"""
    source_manifest = load_source_manifest(paths)
    data_version = research_fingerprint(
        {
            "source_runs": source_manifest,
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
    """使用固定完整年度面板量化共同模式。"""
    runs = select_current_runs(load_eligible_runs(paths))
    latest_year = int(str(as_of_date)[:4])
    years = list(range(START_YEAR, latest_year + 1))
    raw_matrix, raw_excluded = build_annual_metric_matrix(
        runs,
        metric_name="annualized_return",
        years=years,
    )
    excess_matrix, excess_excluded = build_annual_metric_matrix(
        runs,
        metric_name="excess_return",
        years=years,
    )
    common_columns = sorted(
        set(raw_matrix.columns).intersection(excess_matrix.columns)
    )
    if len(common_columns) < 5:
        raise ValueError("共同年度完整实验不足5个")
    raw_matrix = raw_matrix[common_columns]
    excess_matrix = excess_matrix[common_columns]
    style_spreads = _load_style_spreads(paths, as_of_date, years)
    raw_summary = summarize_correlation(raw_matrix)
    excess_summary = summarize_correlation(excess_matrix)
    attribution = build_style_attribution(excess_matrix, style_spreads)
    gate = evaluate_common_mode_gate(excess_summary, attribution)
    result = {
        "as_of_date": str(as_of_date),
        "latest_year": latest_year,
        "eligible_experiment_count": len(runs),
        "complete_experiment_count": len(common_columns),
        "excluded_experiments": sorted(set(raw_excluded + excess_excluded)),
        "raw_return_summary": raw_summary,
        "excess_return_summary": excess_summary,
        "style_attribution": attribution,
        "gate": gate,
        "decision": (
            "FACTOR_ZOO_MIDCAP_COMMON_MODE_CONFIRMED"
            if gate["passed"]
            else "FACTOR_ZOO_COMMON_MODE_NOT_CONFIRMED"
        ),
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    report_path = Path(result["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    return result


def _load_style_spreads(
    paths: RuntimePaths,
    as_of_date: str,
    years: list[int],
) -> pd.DataFrame:
    """从统一基金行情面板构造年度风格价差。"""
    panel = load_fund_portfolio_panel(
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        STYLE_ASSETS,
        start_date=f"{START_YEAR - 1}0101",
        end_date=as_of_date,
    )
    annual = panel.adjusted_close.groupby(
        panel.adjusted_close.index.year
    ).apply(lambda frame: frame.iloc[-1] / frame.iloc[0] - 1.0)
    spreads = pd.DataFrame(index=annual.index)
    spreads["csi500_minus_hs300"] = (
        annual["510500.SH"] - annual["510300.SH"]
    )
    spreads["chinext_minus_hs300"] = (
        annual["159915.SZ"] - annual["510300.SH"]
    )
    return spreads.reindex(years)


def _style_file_versions(paths: RuntimePaths) -> list[str]:
    """把历史基金库与增量基准库绑定到运行指纹。"""
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
    """保存结构化共同模式证据，不改变任何策略状态。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    yearly_path = attempt.output_dir / "yearly_common_mode.csv"
    pd.DataFrame(
        result["style_attribution"]["yearly_common_mode"]
    ).to_csv(yearly_path, index=False)
    correlation_path = attempt.output_dir / "style_correlations.csv"
    pd.DataFrame(
        result["style_attribution"]["strategy_correlations"]
    ).to_csv(correlation_path, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="COMPLETED",
        decision_reason=(
            "因子动物园的年度共同模式和中盘风格归因已完成："
            f"{result['decision']}"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "共同模式归因报告"),
            ExperimentArtifact("yearly", yearly_path, "年度共同模式"),
            ExperimentArtifact(
                "style_correlation",
                correlation_path,
                "实验中盘风格相关",
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
