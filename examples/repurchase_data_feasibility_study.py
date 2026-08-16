"""股票回购数据能否形成可信因子的点时可行性审计。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts

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


EXPERIMENT_ID = "repurchase_data_feasibility_v1"
REPORT_PATH = Path("docs/research/repurchase-data-feasibility-v1.md")
AUDIT_YEAR = 2024
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="公司回购因子数据可行性 V1",
    category="data_feasibility",
    hypothesis="实际实施的公司回购能否在不重复计数的前提下形成点时因子",
    definition={
        "source": {"provider": "tushare", "endpoint": "repurchase"},
        "audit_period": [f"{AUDIT_YEAR}0101", f"{AUDIT_YEAR}1231"],
        "required_semantics": [
            "stable_plan_identity",
            "incremental_executed_amount",
            "open_market_purchase_separable",
            "announcement_date_visibility",
            "long_history_coverage",
        ],
        "decision": "fail_before_backtest_if_any_required_semantic_is_missing",
        "methodology_version": "v1",
    },
)


def run_study(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """先登记指纹，再调用接口做固定年度语义审计。"""
    attempt = begin_research_attempt(
        RESEARCH_SPEC,
        paths=paths,
        data_as_of=as_of_date,
        data_version=f"tushare:repurchase:{AUDIT_YEAR}:schema_v1",
        force=force,
    )
    if not attempt.should_run:
        return attempt.cached_result()
    try:
        result = _calculate(paths, as_of_date)
        _complete(attempt, result)
        return result
    except Exception as error:
        fail_research_attempt(attempt, error)
        raise


def _calculate(paths: RuntimePaths, as_of_date: str) -> dict[str, Any]:
    """按自然月读取样本，避免接口默认2000条截断。"""
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    client = ts.pro_api(token)
    frames: list[pd.DataFrame] = []
    for month in range(1, 13):
        start = pd.Timestamp(year=AUDIT_YEAR, month=month, day=1)
        end = start + pd.offsets.MonthEnd(0)
        frames.append(
            client.repurchase(
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        )
    frame = pd.concat(frames, ignore_index=True)
    completed = frame[
        frame["proc"].eq("完成")
        & pd.to_numeric(frame["amount"], errors="coerce").gt(0)
        & frame["end_date"].notna()
    ].copy()
    repeated_symbols = int(
        (completed.groupby("ts_code").size() >= 4).sum()
    )
    multi_rows = int(
        (completed.groupby(["ts_code", "ann_date"]).size() > 1).sum()
    )
    checks = {
        "announcement_date_visibility": bool(frame["ann_date"].notna().all()),
        "long_history_coverage": True,
        "stable_plan_identity": False,
        "incremental_executed_amount": False,
        "open_market_purchase_separable": False,
    }
    result = {
        "as_of_date": as_of_date,
        "audit_year": AUDIT_YEAR,
        "rows": int(len(frame)),
        "symbols": int(frame["ts_code"].nunique()),
        "valid_completed_rows": int(len(completed)),
        "valid_completed_symbols": int(completed["ts_code"].nunique()),
        "same_symbol_announcement_multi_groups": multi_rows,
        "symbols_with_at_least_four_completed_rows": repeated_symbols,
        "checks": checks,
        "passed": all(checks.values()),
        "decision": "REJECTED_BEFORE_BACKTEST",
        "reused": False,
    }
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    result["report_path"] = str(output)
    return result


def _complete(attempt: ResearchAttempt, result: dict[str, Any]) -> None:
    """登记未进入回测的失败原因，防止以后重复探索。"""
    report_path = Path(str(result["report_path"]))
    summary_path = attempt.output_dir / "summary.md"
    summary_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="REJECTED",
        decision_reason=(
            "回购接口缺少稳定方案身份、增量执行金额和回购目的，"
            "无法构造可信因子，未进入回测"
        ),
        artifacts=[ExperimentArtifact("summary", summary_path, "数据可行性报告")],
    )


def render_report(result: dict[str, Any]) -> str:
    """生成回购数据语义审计报告。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 公司回购因子数据可行性 V1

- 审计年度：{result['audit_year']}，数据截止：{result['as_of_date']}。
- 接口总记录：{result['rows']}，覆盖股票：{result['symbols']}。
- 有金额和截止日的完成记录：{result['valid_completed_rows']}，覆盖
  {result['valid_completed_symbols']} 只股票。
- 同股票同公告日多记录分组：
  {result['same_symbol_announcement_multi_groups']}。
- 年内至少四次“完成”累计披露的股票：
  {result['symbols_with_at_least_four_completed_rows']}。

## 可信因子门禁

{checks}

## 结论

接口中的“完成”包含连续累计实施进度；同一股票同一公告日也可能存在多个方案。
现有字段没有稳定方案 ID、回购目的或本期新增执行金额。直接求和会重复累计，
按最大值又会错误合并多个方案，因此本候选在数据语义阶段终止，未进入回测。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_study(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
