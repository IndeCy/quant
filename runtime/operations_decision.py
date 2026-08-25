"""运行异常决策面。

该模块只读取已有运行事实，回答今天是否需要人工处理；不触发策略、不发通知、不自动下单。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from runtime.operations_observation import build_operations_observation


def build_operations_decision(
    repo_root: Path,
    readiness: Mapping[str, object] | None = None,
    risk_confirmation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """把运行观察和就绪度审计转换成可行动的人工处理决策。"""
    observation = build_operations_observation(repo_root)
    actions = _observation_actions(observation)
    if readiness:
        actions.extend(_readiness_actions(readiness))
    if risk_confirmation:
        actions.extend(_risk_confirmation_actions(risk_confirmation))
    severity = _overall_severity(actions)
    decision = "ACTION_REQUIRED" if actions else "NO_ACTION"
    return {
        "repo_root": str(repo_root.resolve()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision": decision,
        "severity": severity,
        "manual_intervention_required": bool(actions),
        "latest_run_date": str(observation.get("latest_run_date") or ""),
        "latest_activity_date": str(observation.get("latest_activity_date") or ""),
        "latest_activity_type": str(observation.get("latest_activity_type") or ""),
        "summary": observation.get("summary", {}),
        "next_action": _next_action(decision, severity),
        "actions": actions,
    }


def _observation_actions(observation: Mapping[str, object]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for section_name, section in _observation_sections(observation).items():
        if not isinstance(section, Mapping):
            continue
        for item_name, status in section.items():
            if status not in {"WARN", "FAIL"}:
                continue
            result.append(
                {
                    "source": "operations_observation",
                    "category": section_name,
                    "name": str(item_name),
                    "severity": "CRITICAL" if status == "FAIL" else "WARNING",
                    "message": f"{section_name}.{item_name} 状态为 {status}",
                    "suggested_action": _suggest_observation_action(section_name, str(item_name)),
                }
            )
    return result


def _readiness_actions(readiness: Mapping[str, object]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    checks = readiness.get("checks", [])
    if not isinstance(checks, list):
        return result
    for check in checks:
        if not isinstance(check, Mapping) or check.get("status") == "PASS":
            continue
        name = str(check.get("name") or "unknown")
        result.append(
            {
                "source": "readiness",
                "category": "readiness",
                "name": name,
                "severity": "CRITICAL",
                "message": str(check.get("message") or f"{name} 未通过"),
                "suggested_action": _suggest_readiness_action(name),
            }
        )
    return result


def _risk_confirmation_actions(state: Mapping[str, object]) -> list[dict[str, str]]:
    """把未完成的盘前风险确认纳入统一人工处置视图。"""
    result: list[dict[str, str]] = []
    tasks = state.get("tasks", [])
    if not isinstance(tasks, list):
        return result
    for task in tasks:
        if not isinstance(task, Mapping) or task.get("status") != "PENDING_MANUAL_CONFIRM":
            continue
        result.append(
            {
                "source": "pre_market_check",
                "category": "risk_confirmation",
                "name": str(task.get("strategy_id") or "unknown"),
                "severity": str(task.get("severity") or "WARNING"),
                "message": str(task.get("reasons") or "盘前风险待确认"),
                "suggested_action": str(task.get("suggested_action") or "确认风险减仓、原计划撮合或暂停"),
            }
        )
    recovery = state.get("recovery", {})
    recovery_tasks = recovery.get("tasks", []) if isinstance(recovery, Mapping) else []
    for task in recovery_tasks if isinstance(recovery_tasks, list) else []:
        if not isinstance(task, Mapping) or task.get("status") != "PENDING_CONFIRM":
            continue
        result.append(
            {
                "source": "live_risk_guard",
                "category": "risk_recovery",
                "name": str(task.get("strategy_id") or "unknown"),
                "severity": "WARNING",
                "message": str(task.get("reason") or "风险仓位恢复待确认"),
                "suggested_action": "确认分级恢复风险上限，或继续维持当前限仓",
            }
        )
    return result


def _observation_sections(observation: Mapping[str, object]) -> dict[str, object]:
    return {
        "run_artifacts": observation.get("run_artifacts", {}),
        "scheduler": observation.get("scheduler", {}),
        "notification": observation.get("notification", {}),
        "held_reports": observation.get("held_reports", {}),
    }


def _overall_severity(actions: list[dict[str, str]]) -> str:
    if any(item.get("severity") == "CRITICAL" for item in actions):
        return "CRITICAL"
    if actions:
        return "WARNING"
    return "NORMAL"


def _next_action(decision: str, severity: str) -> str:
    if decision == "NO_ACTION":
        return "继续观察，无需人工处理"
    if severity == "CRITICAL":
        return "先处理阻断项，再运行或复核每日流水线"
    return "盘后复核告警项，确认是否需要补跑或修复配置"


def _suggest_observation_action(section: str, item: str) -> str:
    if section == "run_artifacts":
        return "检查最新完整日报目录，必要时补跑每日流水线"
    if section == "scheduler":
        return "检查 launchd 调度器、心跳文件和 scheduler.log"
    if section == "notification":
        return "检查 Bark URL 环境变量或 launchd 配置"
    if section == "held_reports":
        return "重新生成前端报表或检查 reports 目录"
    return f"人工检查 {section}.{item}"


def _suggest_readiness_action(name: str) -> str:
    suggestions = {
        "tushare_token": "配置 TUSHARE_TOKEN 后再运行数据更新",
        "live_market_data": "先修复行情和复权因子增量数据",
        "benchmark_data": "先修复 510300 或上证基准数据",
        "scheduler_job": "重新登记每日调度任务",
        "api_service": "重启本地 API 服务",
        "frontend_service": "重启本地前端服务",
        "scheduler_service": "重启本地调度器服务",
        "notification_channel": "配置 Bark 推送地址",
    }
    return suggestions.get(name, f"根据就绪度提示修复 {name}")
