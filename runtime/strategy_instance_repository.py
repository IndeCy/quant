"""策略实例仓库扩展。"""

from __future__ import annotations

import json
from typing import Any


class StrategyInstanceRepositoryMixin:
    """保存可运行策略实例配置。"""

    def upsert_strategy_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存策略实例，实例启用后可被动态 runner 发现。"""
        strategy_id = str(payload.get("strategy_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        template_id = str(payload.get("template_id") or "").strip()
        if not strategy_id or not name or not template_id:
            raise ValueError("strategy_id, name and template_id are required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_instances(
                    strategy_id, name, template_id, status, enabled, universe,
                    filters_json, factors_json, construction_json, risk_overlay,
                    benchmark, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name=excluded.name, template_id=excluded.template_id,
                    status=excluded.status, enabled=excluded.enabled,
                    universe=excluded.universe, filters_json=excluded.filters_json,
                    factors_json=excluded.factors_json,
                    construction_json=excluded.construction_json,
                    risk_overlay=excluded.risk_overlay, benchmark=excluded.benchmark,
                    config_json=excluded.config_json, modified_at=CURRENT_TIMESTAMP
                """,
                [
                    strategy_id,
                    name,
                    template_id,
                    str(payload.get("status") or "draft"),
                    1 if bool(payload.get("enabled", False)) else 0,
                    str(payload.get("universe") or ""),
                    json.dumps(list(payload.get("filters") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(payload.get("factors") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(dict(payload.get("construction") or {}), ensure_ascii=False, sort_keys=True),
                    str(payload.get("risk_overlay") or ""),
                    str(payload.get("benchmark") or ""),
                    json.dumps(dict(payload.get("config") or {}), ensure_ascii=False, sort_keys=True),
                ],
            )
        return self.load_strategy_instance(strategy_id)

    def load_strategy_instance(self, strategy_id: str) -> dict[str, Any]:
        """读取单个策略实例。"""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM strategy_instances WHERE strategy_id = ?",
                [strategy_id],
            ).fetchone()
        if row is None:
            raise KeyError(strategy_id)
        return self._row_to_dict(row)

    def list_strategy_instances(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """读取策略实例列表。"""
        sql = "SELECT * FROM strategy_instances"
        params: list[Any] = []
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY strategy_id"
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]
