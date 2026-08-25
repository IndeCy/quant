"""Tushare 主题概念成分缓存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import duckdb
import pandas as pd

from runtime.config import get_config_value


@dataclass(frozen=True)
class ConceptUpdateResult:
    """概念缓存更新结果。"""

    index_count: int
    member_count: int
    updated_at: str


class ConceptClient(Protocol):
    """概念数据客户端协议，便于测试替换真实 Tushare。"""

    def ths_index(self) -> pd.DataFrame:
        """读取同花顺指数/概念列表。"""

    def ths_member(self, ts_code: str) -> pd.DataFrame:
        """读取同花顺概念成分。"""

    def dc_index(self) -> pd.DataFrame:
        """读取东方财富板块列表。"""

    def dc_member(self, ts_code: str) -> pd.DataFrame:
        """读取东方财富板块成分。"""


class TushareConceptClient:
    """真实 Tushare 概念客户端。"""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TUSHARE_TOKEN不能为空")
        import tushare as ts

        self._pro = ts.pro_api(token)

    def ths_index(self) -> pd.DataFrame:
        return self._pro.ths_index()

    def ths_member(self, ts_code: str) -> pd.DataFrame:
        return self._pro.ths_member(ts_code=ts_code)

    def dc_index(self) -> pd.DataFrame:
        return self._pro.dc_index()

    def dc_member(self, ts_code: str) -> pd.DataFrame:
        return self._pro.dc_member(ts_code=ts_code)


class ConceptDuckDBStore:
    """本地概念成分缓存。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS concept_index(
                    theme_id VARCHAR,
                    provider VARCHAR,
                    index_code VARCHAR,
                    index_name VARCHAR,
                    keyword VARCHAR,
                    updated_at VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS concept_member(
                    theme_id VARCHAR,
                    provider VARCHAR,
                    index_code VARCHAR,
                    index_name VARCHAR,
                    con_code VARCHAR,
                    con_name VARCHAR,
                    keyword VARCHAR,
                    updated_at VARCHAR
                )
                """
            )

    def replace(self, index_rows: list[dict[str, str]], member_rows: list[dict[str, str]]) -> ConceptUpdateResult:
        """覆盖写入本轮主题概念缓存。"""
        index_rows = _dedupe_rows(index_rows, ["theme_id", "provider", "index_code"])
        member_rows = _dedupe_rows(member_rows, ["theme_id", "provider", "index_code", "con_code"])
        updated_at = datetime.now().isoformat(timespec="seconds")
        for row in index_rows:
            row["updated_at"] = updated_at
        for row in member_rows:
            row["updated_at"] = updated_at
        with self._connect() as con:
            con.execute("DELETE FROM concept_index")
            con.execute("DELETE FROM concept_member")
            if index_rows:
                con.register("concept_index_input", pd.DataFrame(index_rows))
                con.execute("INSERT INTO concept_index SELECT * FROM concept_index_input")
            if member_rows:
                con.register("concept_member_input", pd.DataFrame(member_rows))
                con.execute("INSERT INTO concept_member SELECT * FROM concept_member_input")
        return ConceptUpdateResult(len(index_rows), len(member_rows), updated_at)


def update_opportunity_concept_cache(
    db_path: str | Path,
    theme_keywords: dict[str, list[str]],
    client: ConceptClient | None = None,
) -> ConceptUpdateResult:
    """按主题关键词抓取同花顺和东方财富概念成分并缓存。"""
    concept_client = client or TushareConceptClient(get_config_value("TUSHARE_TOKEN"))
    ths_index = concept_client.ths_index()
    dc_index = concept_client.dc_index()
    index_rows: list[dict[str, str]] = []
    member_rows: list[dict[str, str]] = []
    for theme_id, keywords in theme_keywords.items():
        matches = _match_indices(ths_index, "ths", theme_id, keywords) + _match_indices(dc_index, "dc", theme_id, keywords)
        index_rows.extend(matches)
        for item in matches:
            members = concept_client.ths_member(item["index_code"]) if item["provider"] == "ths" else concept_client.dc_member(item["index_code"])
            member_rows.extend(_member_rows(item, members))
    return ConceptDuckDBStore(db_path).replace(index_rows, member_rows)


def _match_indices(frame: pd.DataFrame, provider: str, theme_id: str, keywords: list[str]) -> list[dict[str, str]]:
    if frame.empty or "name" not in frame.columns or "ts_code" not in frame.columns:
        return []
    rows: list[dict[str, str]] = []
    names = frame["name"].fillna("").astype(str)
    for keyword in keywords:
        matched = frame[names.str.contains(keyword, regex=False)].copy()
        for row in matched.to_dict("records"):
            rows.append(
                {
                    "theme_id": theme_id,
                    "provider": provider,
                    "index_code": str(row.get("ts_code") or ""),
                    "index_name": str(row.get("name") or ""),
                    "keyword": keyword,
                }
            )
    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        unique[(row["theme_id"], row["provider"], row["index_code"])] = row
    return list(unique.values())


def _dedupe_rows(rows: list[dict[str, str]], keys: list[str]) -> list[dict[str, str]]:
    """按业务主键去重，避免日频重复成分放大主题证据。"""
    unique: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(str(row.get(item) or "") for item in keys)
        unique[key] = row
    return list(unique.values())


def _member_rows(index_row: dict[str, str], members: pd.DataFrame) -> list[dict[str, str]]:
    if members.empty:
        return []
    code_col = "con_code" if "con_code" in members.columns else "ts_code"
    name_col = "con_name" if "con_name" in members.columns else "name"
    rows: list[dict[str, str]] = []
    for row in members.to_dict("records"):
        rows.append(
            {
                "theme_id": index_row["theme_id"],
                "provider": index_row["provider"],
                "index_code": index_row["index_code"],
                "index_name": index_row["index_name"],
                "con_code": str(row.get(code_col) or ""),
                "con_name": str(row.get(name_col) or ""),
                "keyword": index_row["keyword"],
                "updated_at": index_row.get("updated_at", ""),
            }
        )
    return rows
