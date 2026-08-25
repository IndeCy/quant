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

    def upsert_research_note(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存通用投研记录，只沉淀最终报告和必要元数据。"""
        note_id = str(payload.get("note_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not note_id or not title or not content:
            raise ValueError("note_id, title and content are required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO research_notes(
                    note_id, title, note_type, linked_type, linked_id,
                    summary, content, tags_json, source, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(note_id) DO UPDATE SET
                    title=excluded.title,
                    note_type=excluded.note_type,
                    linked_type=excluded.linked_type,
                    linked_id=excluded.linked_id,
                    summary=excluded.summary,
                    content=excluded.content,
                    tags_json=excluded.tags_json,
                    source=excluded.source,
                    status=excluded.status,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    note_id,
                    title,
                    str(payload.get("note_type") or "idea"),
                    str(payload.get("linked_type") or ""),
                    str(payload.get("linked_id") or ""),
                    str(payload.get("summary") or ""),
                    content,
                    json.dumps(list(payload.get("tags") or []), ensure_ascii=False),
                    str(payload.get("source") or "manual"),
                    str(payload.get("status") or "active"),
                ],
            )
        return self.load_research_note(note_id)

    def load_research_note(self, note_id: str) -> dict[str, Any]:
        """按 ID 读取单条投研记录。"""
        with self._connect() as con:
            row = con.execute("SELECT * FROM research_notes WHERE note_id = ?", [note_id]).fetchone()
        if row is None:
            raise KeyError(note_id)
        return self._row_to_dict(row)

    def list_research_notes(self, note_type: str | None = None) -> list[dict[str, Any]]:
        """读取投研记录列表，支持按类型筛选。"""
        sql = "SELECT * FROM research_notes"
        params: list[str] = []
        if note_type:
            sql += " WHERE note_type = ?"
            params.append(note_type)
        sql += " ORDER BY modified_at DESC, note_id"
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_opportunity_theme(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存产业机会观察主题。"""
        theme_id = str(payload.get("theme_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not theme_id or not name:
            raise ValueError("theme_id and name are required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO opportunity_themes(
                    theme_id, name, status, stage, horizon_years, thesis_type,
                    thesis, upgrade_rule, disconfirm_rule, linked_note_id, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(theme_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    stage=excluded.stage,
                    horizon_years=excluded.horizon_years,
                    thesis_type=excluded.thesis_type,
                    thesis=excluded.thesis,
                    upgrade_rule=excluded.upgrade_rule,
                    disconfirm_rule=excluded.disconfirm_rule,
                    linked_note_id=excluded.linked_note_id,
                    tags_json=excluded.tags_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    theme_id,
                    name,
                    str(payload.get("status") or "observation"),
                    str(payload.get("stage") or "Observation"),
                    int(payload.get("horizon_years") or 0),
                    str(payload.get("thesis_type") or ""),
                    str(payload.get("thesis") or ""),
                    str(payload.get("upgrade_rule") or ""),
                    str(payload.get("disconfirm_rule") or ""),
                    str(payload.get("linked_note_id") or ""),
                    json.dumps(list(payload.get("tags") or []), ensure_ascii=False),
                ],
            )
        return self.load_opportunity_theme(theme_id)

    def load_opportunity_theme(self, theme_id: str) -> dict[str, Any]:
        """读取单个机会主题及候选股。"""
        with self._connect() as con:
            theme = con.execute("SELECT * FROM opportunity_themes WHERE theme_id = ?", [theme_id]).fetchone()
            if theme is None:
                raise KeyError(theme_id)
            stocks = con.execute(
                """
                SELECT * FROM opportunity_stocks
                WHERE theme_id = ?
                ORDER BY watch_level, symbol
                """,
                [theme_id],
            ).fetchall()
            runs = con.execute(
                """
                SELECT * FROM research_monitor_runs
                WHERE theme_id = ?
                ORDER BY trade_date DESC
                LIMIT 10
                """,
                [theme_id],
            ).fetchall()
        result = self._row_to_dict(theme)
        result["stocks"] = [self._row_to_dict(row) for row in stocks]
        result["monitor_runs"] = [self._row_to_dict(row) for row in runs]
        return result

    def list_opportunity_themes(self) -> list[dict[str, Any]]:
        """读取全部机会主题及其候选股摘要。"""
        with self._connect() as con:
            rows = con.execute("SELECT * FROM opportunity_themes ORDER BY modified_at DESC, theme_id").fetchall()
        return [self.load_opportunity_theme(str(row["theme_id"])) for row in rows]

    def upsert_opportunity_stock(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存机会主题下的候选股票。"""
        theme_id = str(payload.get("theme_id") or "").strip()
        symbol = str(payload.get("symbol") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not theme_id or not symbol or not name:
            raise ValueError("theme_id, symbol and name are required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO opportunity_stocks(
                    theme_id, symbol, name, status, watch_level, chain_role, conviction,
                    source_type, source_detail, verification_status, first_observed_date,
                    thesis, disconfirm_condition, evidence_json, metrics_json, last_monitor_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(theme_id, symbol) DO UPDATE SET
                    name=excluded.name,
                    status=CASE
                        WHEN excluded.status = 'candidate_seed'
                            AND opportunity_stocks.status = 'active'
                            AND opportunity_stocks.verification_status = 'verified'
                            AND excluded.source_type = 'built_in_seed'
                        THEN opportunity_stocks.status
                        ELSE excluded.status
                    END,
                    watch_level=CASE
                        WHEN excluded.metrics_json = '{}' AND excluded.evidence_json = '{}' AND excluded.last_monitor_date = ''
                        THEN opportunity_stocks.watch_level
                        ELSE excluded.watch_level
                    END,
                    chain_role=excluded.chain_role,
                    conviction=excluded.conviction,
                    source_type=CASE
                        WHEN excluded.status = 'candidate_seed'
                            AND opportunity_stocks.status = 'active'
                            AND opportunity_stocks.verification_status = 'verified'
                            AND excluded.source_type = 'built_in_seed'
                        THEN opportunity_stocks.source_type
                        ELSE excluded.source_type
                    END,
                    source_detail=CASE
                        WHEN excluded.status = 'candidate_seed'
                            AND opportunity_stocks.status = 'active'
                            AND opportunity_stocks.verification_status = 'verified'
                            AND excluded.source_type = 'built_in_seed'
                        THEN opportunity_stocks.source_detail
                        ELSE excluded.source_detail
                    END,
                    verification_status=CASE
                        WHEN excluded.status = 'candidate_seed'
                            AND opportunity_stocks.status = 'active'
                            AND opportunity_stocks.verification_status = 'verified'
                            AND excluded.source_type = 'built_in_seed'
                        THEN opportunity_stocks.verification_status
                        ELSE excluded.verification_status
                    END,
                    first_observed_date=excluded.first_observed_date,
                    thesis=excluded.thesis,
                    disconfirm_condition=excluded.disconfirm_condition,
                    evidence_json=CASE
                        WHEN excluded.evidence_json = '{}' THEN opportunity_stocks.evidence_json
                        ELSE excluded.evidence_json
                    END,
                    metrics_json=CASE
                        WHEN excluded.metrics_json = '{}' THEN opportunity_stocks.metrics_json
                        ELSE excluded.metrics_json
                    END,
                    last_monitor_date=CASE
                        WHEN excluded.last_monitor_date = '' THEN opportunity_stocks.last_monitor_date
                        ELSE excluded.last_monitor_date
                    END,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    theme_id,
                    symbol,
                    name,
                    str(payload.get("status") or "active"),
                    str(payload.get("watch_level") or "B"),
                    str(payload.get("chain_role") or ""),
                    str(payload.get("conviction") or ""),
                    str(payload.get("source_type") or ""),
                    str(payload.get("source_detail") or ""),
                    str(payload.get("verification_status") or "unverified"),
                    str(payload.get("first_observed_date") or ""),
                    str(payload.get("thesis") or ""),
                    str(payload.get("disconfirm_condition") or ""),
                    json.dumps(dict(payload.get("evidence") or {}), ensure_ascii=False, sort_keys=True),
                    json.dumps(dict(payload.get("metrics") or {}), ensure_ascii=False, sort_keys=True),
                    str(payload.get("last_monitor_date") or ""),
                ],
            )
        return self.load_opportunity_stock(theme_id, symbol)

    def load_opportunity_stock(self, theme_id: str, symbol: str) -> dict[str, Any]:
        """读取单只机会池股票。"""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM opportunity_stocks WHERE theme_id = ? AND symbol = ?",
                [theme_id, symbol],
            ).fetchone()
        if row is None:
            raise KeyError(f"{theme_id}:{symbol}")
        return self._row_to_dict(row)

    def update_opportunity_stock_monitor(
        self,
        theme_id: str,
        symbol: str,
        watch_level: str,
        metrics: dict[str, Any],
        trade_date: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """写入每日研究监控指标和观察等级。"""
        with self._connect() as con:
            con.execute(
                """
                UPDATE opportunity_stocks
                SET watch_level = ?,
                    evidence_json = ?,
                    metrics_json = ?,
                    last_monitor_date = ?,
                    modified_at = CURRENT_TIMESTAMP
                WHERE theme_id = ? AND symbol = ?
                """,
                [
                    watch_level,
                    json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True),
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    trade_date,
                    theme_id,
                    symbol,
                ],
            )
        return self.load_opportunity_stock(theme_id, symbol)

    def record_research_monitor_run(
        self,
        theme_id: str,
        trade_date: str,
        status: str,
        summary: str,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """记录一次机会池研究监控运行。"""
        run_id = f"{theme_id}:{trade_date}"
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO research_monitor_runs(
                    run_id, trade_date, theme_id, status, summary, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    summary=excluded.summary,
                    metrics_json=excluded.metrics_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [run_id, trade_date, theme_id, status, summary, json.dumps(metrics, ensure_ascii=False, sort_keys=True)],
            )
            row = con.execute("SELECT * FROM research_monitor_runs WHERE run_id = ?", [run_id]).fetchone()
        return self._row_to_dict(row)

    def record_opportunity_direction_ranking(
        self,
        trade_date: str,
        theme: dict[str, Any],
        metrics: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        """记录某交易日某产业方向的强势排行分数。"""
        theme_id = str(theme["theme_id"])
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO opportunity_direction_rankings(
                    trade_date, theme_id, name, status, stage, strength_score,
                    early_signal_score, maturity_score, crowding_score,
                    upgrade_candidate, summary, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, theme_id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    stage=excluded.stage,
                    strength_score=excluded.strength_score,
                    early_signal_score=excluded.early_signal_score,
                    maturity_score=excluded.maturity_score,
                    crowding_score=excluded.crowding_score,
                    upgrade_candidate=excluded.upgrade_candidate,
                    summary=excluded.summary,
                    metrics_json=excluded.metrics_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    trade_date,
                    theme_id,
                    str(theme.get("name") or ""),
                    str(theme.get("status") or ""),
                    str(theme.get("stage") or ""),
                    float(metrics.get("strength_score") or 0.0),
                    float(metrics.get("theme_early_signal_score") or 0.0),
                    float(metrics.get("theme_maturity_score") or 0.0),
                    float(metrics.get("theme_crowding_score") or 0.0),
                    1 if bool(metrics.get("upgrade_candidate")) else 0,
                    summary,
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                ],
            )
            row = con.execute(
                """
                SELECT * FROM opportunity_direction_rankings
                WHERE trade_date = ? AND theme_id = ?
                """,
                [trade_date, theme_id],
            ).fetchone()
        return self._row_to_dict(row)

    def list_opportunity_direction_rankings(self, trade_date: str | None = None) -> list[dict[str, Any]]:
        """读取产业方向强势排行，默认返回最近一次监控结果。"""
        with self._connect() as con:
            target_date = trade_date
            if not target_date:
                row = con.execute("SELECT MAX(trade_date) FROM opportunity_direction_rankings").fetchone()
                target_date = str(row[0]) if row and row[0] else ""
            if not target_date:
                return []
            rows = con.execute(
                """
                SELECT * FROM opportunity_direction_rankings
                WHERE trade_date = ?
                ORDER BY strength_score DESC, theme_id
                """,
                [target_date],
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]
