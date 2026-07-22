"""策略风险上限事件与目标权重约束。

风险策略不修改 Alpha 信号，只把人工确认的仓位上限转换为订单层可执行约束。
解除风险必须写入新的 RELEASE 事件，历史事件不可原地覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Mapping
import uuid

from runtime.schema_version import apply_schema_migrations


ACTIVATE_ACTION = "ACTIVATE"
RELEASE_ACTION = "RELEASE"


@dataclass(frozen=True)
class RiskPolicy:
    """指定日期生效的策略风险上限。"""

    strategy_id: str
    effective_date: str
    max_exposure: float
    action: str
    event_id: str
    source_ack_id: str = ""
    reason: str = ""

    @property
    def active(self) -> bool:
        """只有 ACTIVATE 事件代表当前仍受限。"""
        return self.action == ACTIVATE_ACTION


class RiskPolicyRepository:
    """保存不可变风险事件，并按日期解析当时有效的风险上限。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        apply_schema_migrations(self.database_path)

    def activate(
        self,
        strategy_id: str,
        effective_date: str,
        max_exposure: float,
        *,
        source_ack_id: str = "",
        reason: str = "",
    ) -> RiskPolicy:
        """登记人工确认的风险上限，同一确认重复提交保持幂等。"""
        exposure = float(max_exposure)
        if not 0 <= exposure <= 1:
            raise ValueError("max_exposure must be between 0 and 1")
        event_id = source_ack_id or f"risk-policy:{uuid.uuid4().hex}"
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_risk_policy_events(
                    event_id, strategy_id, effective_date, action,
                    max_exposure, source_ack_id, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    strategy_id=excluded.strategy_id,
                    effective_date=excluded.effective_date,
                    action=excluded.action,
                    max_exposure=excluded.max_exposure,
                    source_ack_id=excluded.source_ack_id,
                    reason=excluded.reason
                """,
                [event_id, strategy_id, _compact_date(effective_date), ACTIVATE_ACTION, exposure, source_ack_id, reason],
            )
        return self.resolve(strategy_id, effective_date) or self._missing_policy(strategy_id, effective_date)

    def release(self, strategy_id: str, effective_date: str, *, reason: str = "") -> RiskPolicy:
        """显式解除风险上限；只能由人工批准的恢复流程调用。"""
        event_id = f"risk-policy-release:{strategy_id}:{_compact_date(effective_date)}"
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_risk_policy_events(
                    event_id, strategy_id, effective_date, action, max_exposure, reason
                ) VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(event_id) DO UPDATE SET reason=excluded.reason
                """,
                [event_id, strategy_id, _compact_date(effective_date), RELEASE_ACTION, reason],
            )
        return RiskPolicy(
            strategy_id,
            _compact_date(effective_date),
            1.0,
            RELEASE_ACTION,
            event_id,
            reason=reason,
        )

    def resolve(self, strategy_id: str, as_of_date: str | None = None) -> RiskPolicy | None:
        """按 as-of 日期读取最近事件，避免用未来风险决定污染历史归因。"""
        where_date = "" if as_of_date is None else "AND effective_date <= ?"
        params: list[object] = [strategy_id]
        if as_of_date is not None:
            params.append(_compact_date(as_of_date))
        with self._connect() as con:
            row = con.execute(
                f"""
                SELECT strategy_id, effective_date, max_exposure, action,
                       event_id, source_ack_id, reason
                FROM strategy_risk_policy_events
                WHERE strategy_id = ? {where_date}
                ORDER BY effective_date DESC, created_at DESC, event_id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        if row is None or str(row[3]) == RELEASE_ACTION:
            return None
        return RiskPolicy(str(row[0]), str(row[1]), float(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6]))

    def list_active(self, as_of_date: str) -> list[RiskPolicy]:
        """列出指定日期仍有效的全部策略上限。"""
        compact = _compact_date(as_of_date)
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT strategy_id, effective_date, max_exposure, action,
                       event_id, source_ack_id, reason
                FROM strategy_risk_policy_events
                WHERE effective_date <= ?
                ORDER BY strategy_id, effective_date DESC, created_at DESC, event_id DESC
                """,
                [compact],
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest.setdefault(str(row[0]), row)
        return [
            RiskPolicy(str(row[0]), str(row[1]), float(row[2]), str(row[3]), str(row[4]), str(row[5]), str(row[6]))
            for row in latest.values()
            if str(row[3]) == ACTIVATE_ACTION
        ]

    def exposure_caps(self, strategy_id: str, dates: list[str]) -> dict[str, float]:
        """批量计算每日风险上限，供监控归因复现历史状态。"""
        if not dates:
            return {}
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT effective_date, action, max_exposure
                FROM strategy_risk_policy_events
                WHERE strategy_id = ? AND effective_date <= ?
                ORDER BY effective_date, created_at, event_id
                """,
                [strategy_id, max(_compact_date(item) for item in dates)],
            ).fetchall()
        events = [(str(row[0]), str(row[1]), float(row[2])) for row in rows]
        caps: dict[str, float] = {}
        current = 1.0
        event_index = 0
        for date in sorted({_compact_date(item) for item in dates}):
            while event_index < len(events) and events[event_index][0] <= date:
                _, action, exposure = events[event_index]
                current = exposure if action == ACTIVATE_ACTION else 1.0
                event_index += 1
            caps[date] = current
        return caps

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.database_path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _missing_policy(strategy_id: str, effective_date: str) -> RiskPolicy:
        raise RuntimeError(f"风险策略写入后无法读取: {strategy_id} {effective_date}")


def apply_risk_cap(target_weights: Mapping[str, float], max_exposure: float | None) -> dict[str, float]:
    """按比例缩放目标权重，保留策略内部的相对配置关系。"""
    weights = {str(symbol): max(float(weight), 0.0) for symbol, weight in target_weights.items()}
    total = sum(weights.values())
    if max_exposure is None or total <= float(max_exposure) or total <= 0:
        return weights
    scale = float(max_exposure) / total
    return {symbol: weight * scale for symbol, weight in weights.items()}


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text
