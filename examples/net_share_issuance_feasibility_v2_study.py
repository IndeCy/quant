"""净股本发行可行性审计的唯一可投股票池分母修正版。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.live_market_view import open_live_market_connection
from data.market_features import load_month_end_signal_dates, materialize_market_features
from data.net_share_issuance import (
    NetShareIssuancePaths,
    attach_net_share_issuance_database,
    create_net_share_issuance_signal_dates,
    materialize_net_share_issuance_asof,
)
from examples.net_share_issuance_feasibility_study import (
    LOCKED_START,
    MIN_CANDIDATES,
    MIN_DISTINGUISHABLE_MONTH_SHARE,
    MIN_MONTH_SHARE,
    MIN_NEGATIVE_ISSUERS,
    STUDY_START,
    _data_version,
    build_latest_distribution,
    build_monthly_coverage,
    evaluate_feasibility,
    load_investable_source,
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


EXPERIMENT_ID = "net_share_issuance_investable_adjustment_feasibility_v2"
REPORT_PATH = Path(
    "docs/research/net-share-issuance-investable-adjustment-feasibility-v2.md"
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="净股本发行可投复权覆盖可行性 V2",
    category="data_feasibility",
    hypothesis="在标准可投股票池内，净股本发行能否形成公司行为清晰的长端候选",
    definition={
        "correction_from": "net_share_issuance_data_feasibility_v1",
        "correction": {
            "adjustment_coverage_denominator": (
                "listed_3y_ex_st_delisted_suspended_bottom20_amount"
            ),
            "reason": "V1 denominator included non-investable financial rows",
            "all_other_gates_unchanged": True,
        },
        "factor": {
            "formula": "annual_total_share/prior_annual_total_share-1",
            "direction": "lower_is_better",
            "annual_reports_only": True,
            "requires_consecutive_years": True,
        },
        "visibility": {
            "rule": "latest_revision_f_ann_date_lte_signal_date",
            "report_freshness_years": [1, 2],
        },
        "corporate_action_gate": {
            "material_adj_factor_change": 0.10,
            "exclude_when_share_and_adj_factor_both_change": True,
        },
        "frozen_gates": {
            "candidate_floor": MIN_CANDIDATES,
            "candidate_month_share": MIN_MONTH_SHARE,
            "negative_issuer_floor": MIN_NEGATIVE_ISSUERS,
            "distinguishable_month_share": MIN_DISTINGUISHABLE_MONTH_SHARE,
            "adjustment_coverage": 0.95,
        },
        "decision": "feasibility_only_no_backtest",
        "no_further_feasibility_variants": True,
        "methodology_version": "v2",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """为分母修正版申请独立指纹后再读取大表。"""
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
    """在可投股票池分母上重新计算覆盖率，不改变其他门槛。"""
    connection = open_live_market_connection(
        paths.base_market_path,
        paths.live_market_increment_path,
        as_of_date=as_of_date,
    )
    try:
        materialize_market_features(connection)
        latest_date = str(
            connection.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        )
        signal_dates = [
            value
            for value in load_month_end_signal_dates(connection)
            if STUDY_START <= value <= latest_date
        ]
        create_net_share_issuance_signal_dates(connection, signal_dates)
        attach_net_share_issuance_database(
            connection,
            NetShareIssuancePaths(paths.balance_sheet_path),
        )
        materialize_net_share_issuance_asof(connection)
        source = load_investable_source(connection)
    finally:
        connection.close()

    diagnostics = build_investable_diagnostics(source)
    available = source["adjustment_available"].fillna(False).astype(bool)
    ambiguous = source["corporate_action_ambiguous"].fillna(False).astype(bool)
    candidates = source[available & ~ambiguous].copy()
    monthly = build_monthly_coverage(candidates)
    distribution = build_latest_distribution(candidates)
    result = evaluate_feasibility(
        monthly,
        distribution,
        diagnostics,
        latest_date,
    )
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    result["monthly_records"] = monthly.to_dict("records")
    result["reused"] = False
    return result


def build_investable_diagnostics(source: pd.DataFrame) -> dict[str, float]:
    """在已通过标准股票池过滤的数据上计算公司行为覆盖。"""
    if source.empty:
        raise ValueError("净股本发行V2没有可投股票池记录")
    publish = source["publish_date"].astype(str)
    prior_publish = source["prior_publish_date"].astype(str)
    signal = source["signal_date"].astype(str)
    adjustment = source["adjustment_available"].fillna(False).astype(bool)
    ambiguous = source["corporate_action_ambiguous"].fillna(False).astype(bool)
    duplicates = len(source) - len(
        source[["signal_date", "symbol"]].drop_duplicates()
    )
    return {
        "visibility_violations": float(
            ((publish > signal) | (prior_publish > signal)).sum()
        ),
        "duplicate_signal_symbol_rows": float(duplicates),
        "adjustment_missing_share": float((~adjustment).mean()),
        "corporate_action_ambiguous_share": float(
            (adjustment & ambiguous).mean()
        ),
    }


def _complete_attempt(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """归档唯一分母修正版，未通过则彻底终止该方向。"""
    monthly = pd.DataFrame(result.pop("monthly_records"))
    monthly_path = attempt.output_dir / "monthly_coverage.csv"
    monthly.to_csv(monthly_path, index=False)
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(render_report(result), encoding="utf-8")
    passed = bool(result["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_FEASIBILITY" if passed else "REJECTED",
        decision_reason=(
            "净股本发行在可投股票池内通过，可进入唯一固定回测"
            if passed
            else "净股本发行V2仍未通过，终止于回测前且不再修订"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary_path, "净股本发行V2可行性报告"),
            ExperimentArtifact("monthly_coverage", monthly_path, "月度可辨识性明细"),
        ],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成修正后可行性报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 净股本发行可投复权覆盖可行性 V2

- 修正：复权覆盖率只在标准可投股票池内计算；其余口径和门槛不变。
- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 总候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 缩股候选最少/中位/最新：{result['negative_count_min']} /
  {result['negative_count_median']:.0f} / {result['negative_count_latest']}。
- 全样本/2022年后可组成无并列Top40月份：
  {result['distinguishable_month_share']:.2%} /
  {result['locked_distinguishable_month_share']:.2%}。
- 最新变化 P1/中位/P99：{distribution['p01']:.2%} /
  {distribution['median']:.2%} / {distribution['p99']:.2%}；
  零变化占比 {distribution['unchanged_share']:.2%}。
- 可投池复权缺失/公司行为歧义：
  {diagnostics['adjustment_missing_share']:.2%} /
  {diagnostics['corporate_action_ambiguous_share']:.2%}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
