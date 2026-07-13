"""本地数据资产目录扫描器。"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import duckdb


DATE_FIELDS = ["trade_date", "cal_date", "f_ann_date", "ann_date", "date"]
SUPPORTED_SUFFIXES = {".duckdb": "duckdb", ".sqlite": "sqlite", ".sqlite3": "sqlite"}


def discover_data_sources(roots: list[str | Path]) -> list[dict[str, Any]]:
    """扫描指定目录下的 DuckDB/SQLite 数据源。"""
    entries: list[dict[str, Any]] = []
    for root in roots:
        base = Path(root).expanduser().resolve()
        if base.is_file():
            candidates = [base]
        else:
            candidates = [
                path
                for suffix in SUPPORTED_SUFFIXES
                for path in base.rglob(f"*{suffix}")
                if path.is_file()
            ]
        for path in sorted(set(candidates)):
            if path.suffix not in SUPPORTED_SUFFIXES:
                continue
            entries.append(inspect_data_source(path))
    return entries


def inspect_data_source(path: str | Path) -> dict[str, Any]:
    """读取单个数据库文件的表结构、行数和最新日期。"""
    source_path = Path(path).expanduser().resolve()
    database_type = SUPPORTED_SUFFIXES.get(source_path.suffix, "unknown")
    try:
        tables = _inspect_duckdb(source_path) if database_type == "duckdb" else _inspect_sqlite(source_path)
        latest_date = _latest_date(tables)
        status = "OK"
        error = ""
    except Exception as exc:  # pragma: no cover - 兜底保护，真实坏库需进入目录而不是中断扫描。
        tables = []
        latest_date = ""
        status = "ERROR"
        error = str(exc)
    return {
        "dataset_id": _dataset_id(source_path),
        "file_path": str(source_path),
        "database_type": database_type,
        "size_bytes": source_path.stat().st_size if source_path.exists() else 0,
        "status": status,
        "latest_date": latest_date,
        "description": "",
        "config": {"error": error} if error else {},
        "tables": tables,
    }


def _inspect_duckdb(path: Path) -> list[dict[str, Any]]:
    """读取 DuckDB 表级元数据。"""
    rows: list[dict[str, Any]] = []
    with duckdb.connect(str(path), read_only=True) as con:
        table_names = [str(item[0]) for item in con.execute("SHOW TABLES").fetchall()]
        for table_name in table_names:
            columns = [str(item[0]) for item in con.execute(f'DESCRIBE "{table_name}"').fetchall()]
            rows.append(_table_metadata(con, table_name, columns, "duckdb"))
    return rows


def _inspect_sqlite(path: Path) -> list[dict[str, Any]]:
    """读取 SQLite 表级元数据。"""
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(path) as con:
        table_names = [
            str(item[0])
            for item in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table_name in table_names:
            columns = [str(item[1]) for item in con.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
            rows.append(_table_metadata(con, table_name, columns, "sqlite"))
    return rows


def _table_metadata(con: Any, table_name: str, columns: list[str], database_type: str) -> dict[str, Any]:
    """生成单表元数据。"""
    date_field = next((field for field in DATE_FIELDS if field in columns), "")
    row_count = int(con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])
    latest_date = ""
    if date_field:
        value = con.execute(f'SELECT MAX("{date_field}") FROM "{table_name}"').fetchone()[0]
        latest_date = str(value or "")
    return {
        "table_name": table_name,
        "row_count": row_count,
        "date_field": date_field,
        "latest_date": latest_date,
        "columns": columns,
        "status": "OK" if database_type in {"duckdb", "sqlite"} else "UNKNOWN",
    }


def _latest_date(tables: list[dict[str, Any]]) -> str:
    """取数据源内最大的日期值。"""
    values = [str(item.get("latest_date") or "") for item in tables if item.get("latest_date")]
    return max(values) if values else ""


def _dataset_id(path: Path) -> str:
    """根据文件名生成稳定数据源 ID。"""
    return path.name.replace(".", "_").replace("-", "_")
