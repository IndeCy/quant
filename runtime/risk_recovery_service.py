"""风险恢复人工确认与 Paper 委托重算应用服务。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Callable

from data.calendar import TradingCalendar
from runtime.local_paper_bridge import replan_paper_orders_for_risk_policy
from runtime.operations_ack import RESOLVED_STATUS, record_operations_ack
from runtime.paths import RuntimePaths
from runtime.risk_policy import RiskPolicyRepository
from runtime.risk_recovery import PENDING_STATUS, RiskRecoveryRepository


APPROVE_DECISION = "APPROVE"
KEEP_DECISION = "KEEP"
ALLOWED_DECISIONS = {APPROVE_DECISION, KEEP_DECISION}


def confirm_risk_recovery(
    paths: RuntimePaths,
    recommendation_id: str,
    decision: str,
    *,
    operator: str = "local_user",
    now: datetime | None = None,
    replan_runner: Callable[..., dict[str, Any]] = replan_paper_orders_for_risk_policy,
) -> dict[str, Any]:
    """确认分级恢复；批准后写风险事件并重算下一交易日未成交委托。"""
    normalized = str(decision).strip().upper()
    if normalized not in ALLOWED_DECISIONS:
        raise ValueError("decision must be APPROVE or KEEP")
    repository = RiskRecoveryRepository(paths.system_state_path)
    recommendation = repository.get(recommendation_id)
    if recommendation is None:
        raise ValueError(f"风险恢复建议不存在: {recommendation_id}")
    if str(recommendation["status"]) != PENDING_STATUS:
        raise ValueError(f"风险恢复建议已处理: {recommendation_id}")

    strategy_id = str(recommendation["strategy_id"])
    ack_id = f"risk-recovery-ack:{recommendation_id}"
    record_operations_ack(
        paths.system_state_path,
        {
            "ack_id": ack_id,
            "trade_date": str(recommendation["trade_date"]),
            "source": "live_risk_guard",
            "category": "risk_recovery",
            "name": strategy_id,
            "severity": "INFO",
            "decision": normalized,
            "message": str(recommendation["reason"]),
            "resolution": (
                f"批准风险上限 {float(recommendation['current_cap']):.0%}→"
                f"{float(recommendation['recommended_cap']):.0%}"
                if normalized == APPROVE_DECISION
                else "继续维持当前风险上限"
            ),
            "operator": operator,
            "status": RESOLVED_STATUS,
        },
    )
    if normalized == KEEP_DECISION:
        decided = repository.decide(recommendation_id, normalized, operator=operator)
        return {"recommendation": decided, "policy": None, "execution": {"status": "KEPT"}}

    effective_date = _next_effective_date(str(recommendation["trade_date"]), now)
    policy_repository = RiskPolicyRepository(paths.system_state_path)
    recommended_cap = float(recommendation["recommended_cap"])
    if recommended_cap >= 1.0:
        policy = policy_repository.release(
            strategy_id,
            effective_date,
            reason=f"人工批准恢复建议 {recommendation_id}",
        )
    else:
        policy = policy_repository.activate(
            strategy_id,
            effective_date,
            recommended_cap,
            source_ack_id=ack_id,
            reason=f"人工批准恢复建议 {recommendation_id}",
        )
    try:
        execution = replan_runner(
            paths=paths,
            strategy_id=strategy_id,
            signal_date=str(recommendation["trade_date"]),
            effective_date=effective_date,
        )
    except Exception as exc:  # 风险上限已安全生效，重算失败留痕并等待人工补跑。
        execution = {"status": "FAILED", "message": str(exc)}
    decided = repository.decide(
        recommendation_id,
        normalized,
        operator=operator,
        execution_status=str(execution.get("status") or ""),
        execution_message=str(execution.get("message") or ""),
    )
    repository.supersede_pending(strategy_id)
    return {"recommendation": decided, "policy": asdict(policy), "execution": execution}


def _next_effective_date(recommendation_date: str, now: datetime | None) -> str:
    """恢复只在下一交易日生效，不能回写当天已经发生的收益。"""
    current = now or datetime.now()
    current_date = current.strftime("%Y%m%d")
    base_date = max(_compact_date(recommendation_date), current_date)
    next_day = TradingCalendar().next_trading_day(base_date)
    if next_day is None:
        raise ValueError(f"无法确定下一交易日: {base_date}")
    return next_day.strftime("%Y%m%d")


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text
