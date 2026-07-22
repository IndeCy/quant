"""风险仓位分级恢复评估与持久化。

恢复层只调整风险仓位上限，不改变策略信号。系统只生成建议，必须经过人工确认后生效。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.risk_policy import RiskPolicy, RiskPolicyRepository
from runtime.risk_rules import classify_strategy_risk
from runtime.schema_version import apply_schema_migrations


PENDING_STATUS = "PENDING"
APPROVED_STATUS = "APPROVED"
KEPT_STATUS = "KEPT"
SUPERSEDED_STATUS = "SUPERSEDED"
STABLE_DAYS_REQUIRED = 3
RECOVERY_VOLATILITY_CEILING = 0.45
RECOVERY_DAILY_RETURN_FLOOR = -0.05
MIN_DRAWDOWN_RECOVERY = 0.02


@dataclass(frozen=True)
class RiskRecoveryAssessment:
    """单个受限策略在指定交易日的恢复判定。"""

    strategy_id: str
    strategy_name: str
    trade_date: str
    policy_effective_date: str
    current_cap: float
    recommended_cap: float
    recommendation_action: str
    current_severity: str
    stable_days_observed: int
    stable_days_required: int
    drawdown_recovery: float
    latest_drawdown: float
    latest_volatility_20: float
    eligible: bool
    reason: str


class RiskRecoveryRepository:
    """保存恢复建议及人工决定，避免每日任务重复推送。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        apply_schema_migrations(self.database_path)

    def create_pending(self, assessment: RiskRecoveryAssessment) -> tuple[dict[str, Any], bool]:
        """幂等创建一条待确认建议，返回记录和是否首次创建。"""
        recommendation_id = _recommendation_id(assessment)
        evidence = json.dumps(asdict(assessment), ensure_ascii=False, sort_keys=True)
        with self._connect() as con:
            cursor = con.execute(
                """
                INSERT OR IGNORE INTO strategy_risk_recovery_recommendations(
                    recommendation_id, strategy_id, trade_date, policy_effective_date,
                    current_cap, recommended_cap, recommendation_action, status,
                    stable_days_observed, stable_days_required, evidence_json, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    recommendation_id,
                    assessment.strategy_id,
                    assessment.trade_date,
                    assessment.policy_effective_date,
                    assessment.current_cap,
                    assessment.recommended_cap,
                    assessment.recommendation_action,
                    PENDING_STATUS,
                    assessment.stable_days_observed,
                    assessment.stable_days_required,
                    evidence,
                    assessment.reason,
                ],
            )
            created = int(cursor.rowcount) > 0
            row = con.execute(
                "SELECT * FROM strategy_risk_recovery_recommendations WHERE recommendation_id = ?",
                [recommendation_id],
            ).fetchone()
        if row is None:
            raise RuntimeError(f"恢复建议写入后无法读取: {recommendation_id}")
        return _row_to_dict(row), created

    def get(self, recommendation_id: str) -> dict[str, Any] | None:
        """按 ID 读取恢复建议。"""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM strategy_risk_recovery_recommendations WHERE recommendation_id = ?",
                [recommendation_id],
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def list_pending(self) -> list[dict[str, Any]]:
        """列出全部待人工确认的恢复建议。"""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM strategy_risk_recovery_recommendations
                WHERE status = ? ORDER BY trade_date DESC, strategy_id
                """,
                [PENDING_STATUS],
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def decide(
        self,
        recommendation_id: str,
        decision: str,
        *,
        operator: str,
        execution_status: str = "",
        execution_message: str = "",
    ) -> dict[str, Any]:
        """保存人工恢复决定；批准和维持限仓都保留审计记录。"""
        status = APPROVED_STATUS if decision == "APPROVE" else KEPT_STATUS
        decided_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute(
                """
                UPDATE strategy_risk_recovery_recommendations
                SET status = ?, decision = ?, operator = ?, decided_at = ?,
                    execution_status = ?, execution_message = ?, modified_at = CURRENT_TIMESTAMP
                WHERE recommendation_id = ?
                """,
                [status, decision, operator, decided_at, execution_status, execution_message, recommendation_id],
            )
        result = self.get(recommendation_id)
        if result is None:
            raise ValueError(f"风险恢复建议不存在: {recommendation_id}")
        return result

    def supersede_pending(self, strategy_id: str, keep_id: str = "") -> int:
        """风险条件变化时撤销旧建议，防止确认过期仓位。"""
        with self._connect() as con:
            cursor = con.execute(
                """
                UPDATE strategy_risk_recovery_recommendations
                SET status = ?, modified_at = CURRENT_TIMESTAMP
                WHERE strategy_id = ? AND status = ? AND recommendation_id <> ?
                """,
                [SUPERSEDED_STATUS, strategy_id, PENDING_STATUS, keep_id],
            )
        return max(int(cursor.rowcount), 0)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.database_path)
        con.row_factory = sqlite3.Row
        return con


def assess_risk_recoveries(paths: RuntimePaths, trade_date: str) -> list[RiskRecoveryAssessment]:
    """评估全部有效风险上限，连续稳定且风险级别改善后才允许分级恢复。"""
    target_date = _compact_date(trade_date)
    policies = RiskPolicyRepository(paths.system_state_path).list_active(target_date)
    monitoring = MonitoringRepository(paths.monitoring_path)
    return [_assess_policy(monitoring, policy, target_date) for policy in policies]


def sync_recovery_recommendations(
    paths: RuntimePaths,
    trade_date: str,
) -> tuple[list[RiskRecoveryAssessment], list[dict[str, Any]]]:
    """把当日评估同步为待确认建议，并返回首次生成、需要 Bark 的记录。"""
    assessments = assess_risk_recoveries(paths, trade_date)
    repository = RiskRecoveryRepository(paths.system_state_path)
    created: list[dict[str, Any]] = []
    for assessment in assessments:
        keep_id = _recommendation_id(assessment) if assessment.eligible else ""
        repository.supersede_pending(assessment.strategy_id, keep_id=keep_id)
        if not assessment.eligible:
            continue
        recommendation, is_new = repository.create_pending(assessment)
        if is_new:
            created.append(recommendation)
    return assessments, created


def build_risk_recovery_state(paths: RuntimePaths, trade_date: str) -> dict[str, Any]:
    """构建前端展示状态，包含恢复进度和待确认建议。"""
    assessments = assess_risk_recoveries(paths, trade_date)
    pending = {
        str(item["strategy_id"]): item
        for item in RiskRecoveryRepository(paths.system_state_path).list_pending()
    }
    tasks: list[dict[str, Any]] = []
    for assessment in assessments:
        item = asdict(assessment)
        recommendation = pending.get(assessment.strategy_id)
        item["recommendation_id"] = str(recommendation["recommendation_id"]) if recommendation else ""
        item["status"] = "PENDING_CONFIRM" if recommendation else "MONITORING"
        tasks.append(item)
    return {
        "trade_date": _compact_date(trade_date),
        "pending_count": sum(item["status"] == "PENDING_CONFIRM" for item in tasks),
        "tasks": tasks,
    }


def _assess_policy(
    monitoring: MonitoringRepository,
    policy: RiskPolicy,
    trade_date: str,
) -> RiskRecoveryAssessment:
    history = monitoring.load_strategy_history(policy.strategy_id)
    history["trade_date"] = history["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    observed = history[
        history["trade_date"].gt(policy.effective_date) & history["trade_date"].le(trade_date)
    ].sort_values("trade_date")
    strategy_name = policy.strategy_id
    if not history.empty:
        strategy_name = str(history.iloc[-1].get("strategy_name") or policy.strategy_id)
    latest = observed.iloc[-1].to_dict() if not observed.empty else {}
    severity, _ = classify_strategy_risk(latest)
    recommended_cap = _next_recovery_cap(policy.max_exposure)
    action = "RELEASE" if recommended_cap >= 1.0 else "INCREASE"
    stable_days = _trailing_stable_days(observed)
    drawdown_recovery = _drawdown_recovery(observed)
    blockers: list[str] = []
    if stable_days < STABLE_DAYS_REQUIRED:
        blockers.append(f"连续稳定 {stable_days}/{STABLE_DAYS_REQUIRED} 个交易日")
    if drawdown_recovery < MIN_DRAWDOWN_RECOVERY:
        blockers.append(f"较受限后低点仅修复 {drawdown_recovery:.2%}，需至少 2%")
    if policy.max_exposure < 0.70 and severity == "CRITICAL":
        blockers.append("当前仍为 CRITICAL，暂不提高风险上限")
    if policy.max_exposure >= 0.70 and severity != "NORMAL":
        blockers.append("完全解除前必须恢复为 NORMAL")
    eligible = not blockers
    reason = (
        f"连续稳定{stable_days}日，回撤修复{drawdown_recovery:.2%}，"
        f"风险状态{severity}，建议{policy.max_exposure:.0%}→{recommended_cap:.0%}"
        if eligible
        else "；".join(blockers)
    )
    return RiskRecoveryAssessment(
        strategy_id=policy.strategy_id,
        strategy_name=strategy_name,
        trade_date=trade_date,
        policy_effective_date=policy.effective_date,
        current_cap=policy.max_exposure,
        recommended_cap=recommended_cap,
        recommendation_action=action,
        current_severity=severity,
        stable_days_observed=stable_days,
        stable_days_required=STABLE_DAYS_REQUIRED,
        drawdown_recovery=drawdown_recovery,
        latest_drawdown=float(latest.get("drawdown") or 0.0),
        latest_volatility_20=float(latest.get("volatility_20") or 0.0),
        eligible=eligible,
        reason=reason,
    )


def _trailing_stable_days(frame: Any) -> int:
    count = 0
    for _, row in frame.sort_values("trade_date", ascending=False).iterrows():
        daily_return = float(row.get("daily_return") or 0.0)
        volatility = float(row.get("volatility_20") or 0.0)
        if daily_return <= RECOVERY_DAILY_RETURN_FLOOR or volatility >= RECOVERY_VOLATILITY_CEILING:
            break
        count += 1
    return count


def _drawdown_recovery(frame: Any) -> float:
    if frame.empty:
        return 0.0
    drawdowns = frame["drawdown"].fillna(0.0).astype(float)
    return max(float(drawdowns.iloc[-1] - drawdowns.min()), 0.0)


def _next_recovery_cap(current_cap: float) -> float:
    if current_cap < 0.50:
        return 0.50
    if current_cap < 0.70:
        return 0.70
    return 1.0


def _recommendation_id(assessment: RiskRecoveryAssessment) -> str:
    return (
        f"risk-recovery:{assessment.trade_date}:{assessment.strategy_id}:"
        f"{int(round(assessment.recommended_cap * 100))}"
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text
