"""策略生命周期状态机。"""

from __future__ import annotations

from typing import Any


class StrategyLifecycleError(RuntimeError):
    """策略生命周期校验失败。"""


RUNNABLE_STATUSES = {"research_observation", "paper", "shadow_live", "live"}
VALID_STATUSES = {"draft", "research", "research_observation", "paper", "shadow_live", "live", "paused", "retired"}
ALLOWED_TRANSITIONS = {
    "draft": {"research", "research_observation", "paused", "retired"},
    "research": {"research_observation", "paper", "paused", "retired"},
    "research_observation": {"paper", "paused", "retired"},
    "paper": {"shadow_live", "paused", "retired"},
    "shadow_live": {"live", "paused", "retired"},
    "live": {"paused", "retired"},
    "paused": {"research_observation", "paper", "retired"},
    "retired": set(),
}


def validate_transition(current_status: str, target_status: str) -> None:
    """校验策略状态流转是否合法。"""
    if current_status not in VALID_STATUSES:
        raise StrategyLifecycleError(f"unknown current status: {current_status}")
    if target_status not in VALID_STATUSES:
        raise StrategyLifecycleError(f"unknown target status: {target_status}")
    if target_status == current_status:
        return
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise StrategyLifecycleError(f"invalid transition: {current_status} -> {target_status}")


def is_runnable_status(status: str) -> bool:
    """判断策略状态是否允许进入每日批处理。"""
    return status in RUNNABLE_STATUSES


def validate_strategy_for_run(strategy: dict[str, Any], contract_validation: dict[str, Any]) -> None:
    """运行态策略启用前校验。"""
    status = str(strategy.get("status") or "")
    if not is_runnable_status(status):
        raise StrategyLifecycleError(f"strategy status is not runnable: {status}")
    if not strategy.get("template_id"):
        raise StrategyLifecycleError("template_id is required")
    if not strategy.get("benchmark"):
        raise StrategyLifecycleError("benchmark is required")
    if not strategy.get("construction"):
        raise StrategyLifecycleError("construction is required")
    missing = list(contract_validation.get("missing_factors") or [])
    if missing and str(strategy.get("template_id") or "") != "opportunity_observer":
        raise StrategyLifecycleError(f"missing factor contracts: {missing}")
