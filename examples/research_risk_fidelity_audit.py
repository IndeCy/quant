"""研究风险层实现一致性审计与历史复验状态登记。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
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
from scripts.check_research_risk_fidelity import find_research_risk_errors


EXPERIMENT_ID = "research_risk_fidelity_audit_v1"
REPORT_PATH = Path("docs/research/research-risk-fidelity-audit-v1.md")
PENDING_MODULES = (
    "abnormal_inventory_accumulation_study.py",
    "accrual_quality_study.py",
    "amihud_illiquidity_study.py",
    "asset_turnover_change_study.py",
    "block_trade_premium_study.py",
    "capitulation_volume_reversal_study.py",
    "cash_conversion_cycle_study.py",
    "dividend_growth_persistence_study.py",
    "dividend_growth_persistence_v2_study.py",
    "dividend_growth_persistence_v3_study.py",
    "downside_beta_study.py",
    "earnings_express_acceleration_study.py",
    "earnings_express_acceleration_v2_study.py",
    "earnings_forecast_momentum_study.py",
    "earnings_stability_study.py",
    "earnings_surprise_strategy_study.py",
    "fund_ownership_breadth_study.py",
    "gross_margin_expansion_study.py",
    "gross_profitability_study.py",
    "insider_net_buying_study.py",
    "intraday_strength_study.py",
    "low_asset_growth_study.py",
    "low_max_lottery_study.py",
    "margin_flow_strategy_study.py",
    "monthly_seasonality_study.py",
    "net_debt_financing_study.py",
    "operating_profitability_study.py",
    "piotroski_value_study.py",
    "price_high_proximity_study.py",
    "profitability_floor_study.py",
    "residual_volatility_study.py",
    "shareholder_concentration_study.py",
    "signed_amount_pressure_study.py",
    "smooth_momentum_study.py",
)
REVALIDATED_MODULES = (
    "low_return_skewness_study.py",
    "factor_multifold_revalidation.py",
    "gross_margin_expansion_v2_study.py",
    "price_high_breakout_study.py",
)
INTENTIONAL_FIXED_MODULES = (
    "cross_asset_dual_momentum_stateful_risk_study.py",
    "cross_asset_dual_momentum_study.py",
    "cross_asset_independent_trend_study.py",
    "gold_bond_equal_defensive_study.py",
    "gold_bond_equal_robustness_study.py",
    "gold_trend_bond_switch_study.py",
    "three_asset_equal_all_weather_study.py",
    "three_asset_inverse_volatility_study.py",
)
RESEARCH_SPEC = ResearchSpec(
    experiment_id=EXPERIMENT_ID,
    name="研究风险层实现一致性审计 V1",
    category="research_governance",
    hypothesis="历史研究的风险层声明、指纹与实际回测模式是否一致",
    definition={
        "audit": {
            "parser": "python_ast",
            "requires_explicit_grid_mode": True,
            "fixed_must_not_receive_grid_thresholds": True,
            "declared_mode_must_match_literal_call": True,
        },
        "affected_historical_runs": {
            "total": len(PENDING_MODULES) + len(REVALIDATED_MODULES),
            "pending_modules": list(PENDING_MODULES),
            "revalidated_modules": list(REVALIDATED_MODULES),
        },
        "intentional_fixed_modules": list(INTENTIONAL_FIXED_MODULES),
        "decision": "pending_runs_are_not_valid_risk_overlay_evidence",
        "methodology_version": "v1",
    },
)


def run_audit(
    paths: RuntimePaths,
    as_of_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """登记审计指纹，检查源码并更新实验复验状态。"""
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
    """执行静态审计并把未重跑实验标记为需要复验。"""
    errors = find_research_risk_errors(paths.root)
    if errors:
        raise ValueError(f"研究风险层围栏仍有 {len(errors)} 个错误")
    repository = SystemRepository(paths.system_state_path)
    pending, newly_revalidated = _classify_pending(
        repository,
        paths.root,
    )
    revalidated = [
        *_load_revalidated(
            repository,
            paths.root,
            REVALIDATED_MODULES,
        ),
        *newly_revalidated,
    ]
    decision = (
        "REVALIDATION_COMPLETE"
        if not pending
        else "REVALIDATION_IN_PROGRESS"
    )
    result = {
        "as_of_date": str(as_of_date),
        "static_check_passed": True,
        "affected_count": len(PENDING_MODULES) + len(REVALIDATED_MODULES),
        "pending_count": len(pending),
        "revalidated_count": len(revalidated),
        "pending": pending,
        "revalidated": revalidated,
        "intentional_fixed_modules": list(INTENTIONAL_FIXED_MODULES),
        "decision": decision,
        "report_path": str(paths.root / REPORT_PATH),
        "reused": False,
    }
    output = paths.root / REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    return result


def _classify_pending(
    repository: SystemRepository,
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按治理状态与最新指纹把历史实验拆成待复验和已复验。"""
    catalog = {
        str(item["experiment_id"]): item
        for item in repository.list_experiments()
    }
    pending: list[dict[str, Any]] = []
    revalidated: list[dict[str, Any]] = []
    for module in PENDING_MODULES:
        experiment_id = _experiment_id(root / "examples" / module)
        item = catalog.get(experiment_id)
        if item is None:
            pending.append(
                {
                    "module": module,
                    "experiment_id": experiment_id,
                    "status": "missing_history",
                }
            )
            continue
        fingerprint_matches = (
            str(item.get("definition_fingerprint") or "")
            == str(item.get("latest_definition_fingerprint") or "")
        )
        if (
            str(item.get("status") or "") != "needs_revalidation"
            and fingerprint_matches
        ):
            revalidated.append(
                _revalidated_record(module, experiment_id, item)
            )
            continue
        if str(item.get("status") or "") == "needs_revalidation":
            pending.append(_pending_record(module, experiment_id, item))
            continue
        repository.upsert_experiment(
            {
                "experiment_id": experiment_id,
                "name": item["name"],
                "category": item["category"],
                "status": "needs_revalidation",
                "owner": item["owner"],
                "description": item["description"],
                "hypothesis": item["hypothesis"],
                "definition_fingerprint": item["definition_fingerprint"],
                "config": json.loads(item.get("config_json") or "{}"),
            }
        )
        pending.append(_pending_record(module, experiment_id, item))
    return pending, revalidated


def _load_revalidated(
    repository: SystemRepository,
    root: Path,
    modules: tuple[str, ...],
) -> list[dict[str, Any]]:
    """核对修正后运行指纹已经成为每个实验的最新结果。"""
    catalog = {
        str(item["experiment_id"]): item
        for item in repository.list_experiments()
    }
    records: list[dict[str, Any]] = []
    for module in modules:
        experiment_id = _experiment_id(root / "examples" / module)
        item = catalog.get(experiment_id)
        if item is None:
            raise ValueError(f"复验实验未登记: {experiment_id}")
        fingerprint_matches = (
            str(item.get("definition_fingerprint") or "")
            == str(item.get("latest_definition_fingerprint") or "")
        )
        if not fingerprint_matches:
            raise ValueError(f"复验指纹不是最新定义: {experiment_id}")
        records.append(_revalidated_record(module, experiment_id, item))
    return records


def _pending_record(
    module: str,
    experiment_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    """构造待复验实验摘要。"""
    return {
        "module": module,
        "experiment_id": experiment_id,
        "status": "needs_revalidation",
        "latest_run_id": item.get("latest_run_id") or "",
        "latest_outcome": item.get("latest_outcome") or "",
    }


def _revalidated_record(
    module: str,
    experiment_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    """构造当前定义与最新运行一致的复验摘要。"""
    return {
        "module": module,
        "experiment_id": experiment_id,
        "status": "revalidated",
        "latest_run_id": item.get("latest_run_id") or "",
        "latest_outcome": item.get("latest_outcome") or "",
        "fingerprint_matches_current": True,
    }


def _experiment_id(path: Path) -> str:
    """从源码常量读取实验ID，避免导入时触发研究副作用。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id in {"STRATEGY_ID", "EXPERIMENT_ID"}
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(
            node.value.value,
            str,
        ):
            return node.value.value
    raise ValueError(f"研究入口缺少静态实验ID: {path}")


def render_report(result: dict[str, Any]) -> str:
    """生成可读的修复范围和复验队列。"""
    revalidated_rows = "\n".join(
        f"| {item['experiment_id']} | {item['latest_outcome']} | "
        f"`{item['latest_run_id']}` |"
        for item in result["revalidated"]
    )
    pending_rows = "\n".join(
        f"| {item['experiment_id']} | {item['status']} | "
        f"{item.get('latest_outcome', '')} |"
        for item in result["pending"]
    )
    return f"""# 研究风险层实现一致性审计 V1

- 审计日期：{result['as_of_date']}。
- 受影响历史研究：{result['affected_count']}项。
- 已按新指纹重跑：{result['revalidated_count']}项。
- 待复验：{result['pending_count']}项。
- 静态围栏：{'PASS' if result['static_check_passed'] else 'FAIL'}。

## 已复验

| 实验 | 最新结论 | 最新运行 |
|---|---|---|
{revalidated_rows}

## 待复验

| 实验 | 治理状态 | 旧结论 |
|---|---|---|
{pending_rows}

## 口径说明

- `GRID`：20日组合波动率超过45%时，下一交易日目标仓位降至30%。
- `FIXED`：不应用该波动率覆盖层；传入阈值参数也不会生效。
- 待复验实验的旧结果仍保留用于审计，但不能作为风险层有效性证据。
- 明确声明无覆盖层或使用独立状态控制器的研究不属于缺陷。

结论：源码错配已经修复并由总验收阻断复发；历史研究仍在分批复验，
完成前不得用待复验结果晋级生产策略。
"""


def _complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
) -> None:
    """归档审计报告和结构化复验清单。"""
    report = Path(str(result["report_path"]))
    summary = attempt.output_dir / "summary.md"
    summary.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    queue = attempt.output_dir / "revalidation_queue.csv"
    pd.DataFrame(result["pending"]).to_csv(queue, index=False)
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome=str(result["decision"]),
        decision_reason=(
            f"风险层源码已修复，剩余{result['pending_count']}项历史研究待复验"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "风险层一致性审计"),
            ExperimentArtifact("revalidation_queue", queue, "待复验队列"),
        ],
    )


def _data_version(paths: RuntimePaths) -> str:
    """用受影响源码和实验状态共同绑定审计版本。"""
    root = paths.root
    digest = hashlib.sha256()
    names = [
        *PENDING_MODULES,
        *REVALIDATED_MODULES,
        *INTENTIONAL_FIXED_MODULES,
    ]
    for name in sorted(set(names)):
        path = root / "examples" / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes())
    digest.update(
        (root / "scripts" / "check_research_risk_fidelity.py").read_bytes()
    )
    repository = SystemRepository(paths.system_state_path)
    catalog = {
        str(item["experiment_id"]): item
        for item in repository.list_experiments()
    }
    for name in sorted(
        set(PENDING_MODULES) | set(REVALIDATED_MODULES)
    ):
        experiment_id = _experiment_id(root / "examples" / name)
        item = catalog.get(experiment_id, {})
        state = {
            "experiment_id": experiment_id,
            "status": item.get("status") or "",
            "definition_fingerprint": (
                item.get("definition_fingerprint") or ""
            ),
            "latest_run_id": item.get("latest_run_id") or "",
            "latest_definition_fingerprint": (
                item.get("latest_definition_fingerprint") or ""
            ),
        }
        digest.update(
            json.dumps(state, sort_keys=True).encode("utf-8")
        )
    return digest.hexdigest()


def main() -> None:
    """运行命令行审计入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of-date",
        default=pd.Timestamp.today().strftime("%Y%m%d"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(run_audit(get_runtime_paths(), args.as_of_date, force=args.force))


if __name__ == "__main__":
    main()
