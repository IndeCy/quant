"""Quality Cleanup + Volatility Overlay 每日Paper状态持久化。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class QualityPaperSnapshot:
    """冻结策略某个交易日收盘后的理论目标。"""

    trade_date: str
    selection_date: str
    exposure: float
    volatility20: float
    risk_state: str
    target_weights: dict[str, float]
    warnings: list[str]


def build_target_weights(symbols: list[str], exposure: float) -> dict[str, float]:
    """Top20仍然等权，风险层只控制组合总仓位。"""
    if not symbols:
        return {}
    if not 0 <= exposure <= 1:
        raise ValueError("exposure必须在0到1之间")
    weight = float(exposure) / len(symbols)
    return {symbol: weight for symbol in symbols}


class QualityPaperStore:
    """SQLite保存每日理论仓位，便于长期复盘和漂移分析。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_overlay_snapshot (
                    trade_date TEXT PRIMARY KEY,
                    selection_date TEXT NOT NULL,
                    exposure REAL NOT NULL,
                    volatility20 REAL NOT NULL,
                    risk_state TEXT NOT NULL,
                    target_weights TEXT NOT NULL,
                    warnings TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, snapshot: QualityPaperSnapshot) -> None:
        """以交易日为主键覆盖，重跑不会制造重复记录。"""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO quality_overlay_snapshot(
                    trade_date, selection_date, exposure, volatility20,
                    risk_state, target_weights, warnings
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    selection_date=excluded.selection_date,
                    exposure=excluded.exposure,
                    volatility20=excluded.volatility20,
                    risk_state=excluded.risk_state,
                    target_weights=excluded.target_weights,
                    warnings=excluded.warnings,
                    modified_at=CURRENT_TIMESTAMP
                """,
                (
                    snapshot.trade_date,
                    snapshot.selection_date,
                    snapshot.exposure,
                    snapshot.volatility20,
                    snapshot.risk_state,
                    json.dumps(snapshot.target_weights, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot.warnings, ensure_ascii=False),
                ),
            )

    def load(self, trade_date: str) -> QualityPaperSnapshot | None:
        """按交易日读取快照。"""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT trade_date, selection_date, exposure, volatility20,
                       risk_state, target_weights, warnings
                FROM quality_overlay_snapshot WHERE trade_date = ?
                """,
                [trade_date],
            ).fetchone()
        if row is None:
            return None
        return QualityPaperSnapshot(
            trade_date=str(row[0]),
            selection_date=str(row[1]),
            exposure=float(row[2]),
            volatility20=float(row[3]),
            risk_state=str(row[4]),
            target_weights={key: float(value) for key, value in json.loads(row[5]).items()},
            warnings=list(json.loads(row[6])),
        )

    def load_latest_before(self, trade_date: str) -> QualityPaperSnapshot | None:
        """读取指定交易日前最近一次快照。"""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT trade_date
                FROM quality_overlay_snapshot
                WHERE trade_date < ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [trade_date],
            ).fetchone()
        if row is None:
            return None
        return self.load(str(row[0]))

    def count(self) -> int:
        """返回快照数量。"""
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM quality_overlay_snapshot").fetchone()[0])
