"""研究想法仓库扩展。"""

from __future__ import annotations

import json
from typing import Any


class ResearchIdeaRepositoryMixin:
    """保存自然语言因子和策略想法。"""

    def upsert_factor_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存自然语言因子想法，先沉淀为研究资产。"""
        idea_id = str(payload.get("idea_id") or "").strip()
        if not idea_id or not str(payload.get("title") or "").strip():
            raise ValueError("idea_id and title are required")
        values = [
            idea_id,
            str(payload.get("title") or ""),
            str(payload.get("raw_description") or ""),
            str(payload.get("source") or ""),
            str(payload.get("hypothesis") or ""),
            json.dumps(list(payload.get("required_data") or []), ensure_ascii=False),
            str(payload.get("as_of_requirement") or ""),
            str(payload.get("direction") or ""),
            str(payload.get("status") or "draft"),
        ]
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO factor_ideas(
                    idea_id, title, raw_description, source, hypothesis, required_data_json,
                    as_of_requirement, direction, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idea_id) DO UPDATE SET
                    title=excluded.title, raw_description=excluded.raw_description,
                    source=excluded.source, hypothesis=excluded.hypothesis,
                    required_data_json=excluded.required_data_json,
                    as_of_requirement=excluded.as_of_requirement, direction=excluded.direction,
                    status=excluded.status, modified_at=CURRENT_TIMESTAMP
                """,
                values,
            )
        return self.load_factor_idea(idea_id)

    def load_factor_idea(self, idea_id: str) -> dict[str, Any]:
        """按 ID 读取单个因子想法。"""
        with self._connect() as con:
            row = con.execute("SELECT * FROM factor_ideas WHERE idea_id = ?", [idea_id]).fetchone()
        if row is None:
            raise KeyError(idea_id)
        return self._row_to_dict(row)

    def list_factor_ideas(self) -> list[dict[str, Any]]:
        """读取因子想法列表。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM factor_ideas ORDER BY modified_at DESC, idea_id").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_strategy_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存自然语言策略想法，后续再结构化为策略实例。"""
        idea_id = str(payload.get("idea_id") or "").strip()
        if not idea_id or not str(payload.get("title") or "").strip():
            raise ValueError("idea_id and title are required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO strategy_ideas(
                    idea_id, title, raw_description, source, hypothesis,
                    candidate_template, required_factors_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idea_id) DO UPDATE SET
                    title=excluded.title, raw_description=excluded.raw_description,
                    source=excluded.source, hypothesis=excluded.hypothesis,
                    candidate_template=excluded.candidate_template,
                    required_factors_json=excluded.required_factors_json,
                    status=excluded.status, modified_at=CURRENT_TIMESTAMP
                """,
                [
                    idea_id,
                    str(payload.get("title") or ""),
                    str(payload.get("raw_description") or ""),
                    str(payload.get("source") or ""),
                    str(payload.get("hypothesis") or ""),
                    str(payload.get("candidate_template") or ""),
                    json.dumps(list(payload.get("required_factors") or []), ensure_ascii=False),
                    str(payload.get("status") or "draft"),
                ],
            )
        return self.load_strategy_idea(idea_id)

    def load_strategy_idea(self, idea_id: str) -> dict[str, Any]:
        """按 ID 读取单个策略想法。"""
        with self._connect() as con:
            row = con.execute("SELECT * FROM strategy_ideas WHERE idea_id = ?", [idea_id]).fetchone()
        if row is None:
            raise KeyError(idea_id)
        return self._row_to_dict(row)

    def list_strategy_ideas(self) -> list[dict[str, Any]]:
        """读取策略想法列表。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM strategy_ideas ORDER BY modified_at DESC, idea_id").fetchall()
        return [self._row_to_dict(row) for row in rows]
