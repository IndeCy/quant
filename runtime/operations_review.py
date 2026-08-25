"""运维闭环复盘指标。

聚合当前操作判断与人工确认记录，用于评估告警是否已经被确认处理。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from runtime.operations_ack import list_operations_ack
from runtime.operations_decision import build_operations_decision


def build_operations_review(
    repo_root: Path,
    db_path: Path,
    readiness: Mapping[str, object] | None = None,
    risk_confirmation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """生成运行决策和人工确认之间的闭环指标。"""
    decision = build_operations_decision(repo_root, readiness, risk_confirmation)
    actions = [item for item in decision.get("actions", []) if isinstance(item, dict)]
    acknowledgements = list_operations_ack(db_path, limit=100)
    ack_keys = {_action_key(item) for item in acknowledgements}
    acknowledged = [item for item in actions if _action_key(item) in ack_keys]
    unacknowledged = [item for item in actions if _action_key(item) not in ack_keys]
    closure_status = "CLOSED" if not unacknowledged else "OPEN"
    return {
        "repo_root": str(repo_root.resolve()),
        "closure_status": closure_status,
        "latest_decision": decision.get("decision", ""),
        "latest_severity": decision.get("severity", ""),
        "latest_run_date": decision.get("latest_run_date", ""),
        "latest_activity_date": decision.get("latest_activity_date", ""),
        "current_action_count": len(actions),
        "acknowledged_action_count": len(acknowledged),
        "unacknowledged_action_count": len(unacknowledged),
        "acknowledgement_count": len(acknowledgements),
        "latest_ack_at": str(acknowledgements[0].get("created_at") or "") if acknowledgements else "",
        "unacknowledged_actions": unacknowledged,
    }


def _action_key(item: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("source") or ""),
        str(item.get("category") or ""),
        str(item.get("name") or ""),
    )
