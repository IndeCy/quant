"""Data Catalog 仓库方法。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DataCatalogRepositoryMixin:
    """保存本地数据库资产目录，降低迁移和排障成本。"""

    def upsert_data_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        """登记一个数据源及其表级信息。"""
        dataset_id = str(payload.get("dataset_id") or "").strip()
        if not dataset_id:
            raise ValueError("dataset_id is required")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO data_sources(
                    dataset_id, file_path, database_type, size_bytes,
                    status, latest_date, description, config_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    file_path=excluded.file_path,
                    database_type=excluded.database_type,
                    size_bytes=excluded.size_bytes,
                    status=excluded.status,
                    latest_date=excluded.latest_date,
                    description=excluded.description,
                    config_json=excluded.config_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [
                    dataset_id,
                    str(payload.get("file_path") or ""),
                    str(payload.get("database_type") or ""),
                    int(payload.get("size_bytes") or 0),
                    str(payload.get("status") or "UNKNOWN"),
                    str(payload.get("latest_date") or ""),
                    str(payload.get("description") or ""),
                    json.dumps(dict(payload.get("config") or {}), ensure_ascii=False, sort_keys=True),
                ],
            )
            con.execute("DELETE FROM data_source_tables WHERE dataset_id = ?", [dataset_id])
            con.executemany(
                """
                INSERT INTO data_source_tables(
                    dataset_id, table_name, row_count, date_field,
                    latest_date, columns_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [_table_params(dataset_id, item) for item in payload.get("tables", [])],
            )
            row = con.execute("SELECT * FROM data_sources WHERE dataset_id = ?", [dataset_id]).fetchone()
        return self._row_to_dict(row)

    def list_data_sources(self) -> list[dict[str, Any]]:
        """读取数据源目录。"""
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM data_sources ORDER BY status DESC, dataset_id"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def load_data_source(self, dataset_id: str) -> dict[str, Any] | None:
        """读取单个数据源及表结构。"""
        with self._connect() as con:
            source = con.execute(
                "SELECT * FROM data_sources WHERE dataset_id = ?",
                [dataset_id],
            ).fetchone()
            if source is None:
                return None
            table_rows = con.execute(
                """
                SELECT * FROM data_source_tables
                WHERE dataset_id = ?
                ORDER BY table_name
                """,
                [dataset_id],
            ).fetchall()
        result = self._row_to_dict(source)
        result["tables"] = [_parse_table_row(row) for row in table_rows]
        return result


def _table_params(dataset_id: str, item: dict[str, Any]) -> tuple[Any, ...]:
    """把表级信息转成 SQLite 参数。"""
    return (
        dataset_id,
        str(item.get("table_name") or ""),
        int(item.get("row_count") or 0),
        str(item.get("date_field") or ""),
        str(item.get("latest_date") or ""),
        json.dumps(list(item.get("columns") or []), ensure_ascii=False),
        str(item.get("status") or "UNKNOWN"),
    )


def _parse_table_row(row: Any) -> dict[str, Any]:
    """解析表级字段列表。"""
    result = dict(row)
    result["columns"] = json.loads(result.pop("columns_json") or "[]")
    return result
