"""游资主线识别板块映射读取。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

SECTOR_MAP_COLUMNS = ["ts_code", "sector_name"]


def load_hot_money_sector_map(
    concept_path: str | Path,
    industry_path: str | Path,
) -> pd.DataFrame:
    """读取本地概念成分和行业缓存，生成主线识别用板块映射。"""
    concept = _load_concept_map(Path(concept_path))
    industry = _load_industry_map(Path(industry_path))
    if concept.empty:
        return industry
    if industry.empty:
        return concept
    concept_codes = set(concept["ts_code"].astype(str))
    fallback = industry[~industry["ts_code"].astype(str).isin(concept_codes)]
    return pd.concat([concept, fallback], ignore_index=True).drop_duplicates(SECTOR_MAP_COLUMNS)


def _load_concept_map(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=SECTOR_MAP_COLUMNS)
    with duckdb.connect(str(path), read_only=True) as con:
        if not _has_table(con, "concept_member"):
            return pd.DataFrame(columns=SECTOR_MAP_COLUMNS)
        frame = con.execute(
            """
            SELECT con_code AS ts_code, index_name AS sector_name
            FROM concept_member
            WHERE COALESCE(con_code, '') <> ''
              AND COALESCE(index_name, '') <> ''
            """
        ).fetchdf()
    return frame[SECTOR_MAP_COLUMNS].drop_duplicates()


def _load_industry_map(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=SECTOR_MAP_COLUMNS)
    with duckdb.connect(str(path), read_only=True) as con:
        if not _has_table(con, "stock_industry"):
            return pd.DataFrame(columns=SECTOR_MAP_COLUMNS)
        frame = con.execute(
            """
            SELECT ts_code, industry AS sector_name
            FROM stock_industry
            WHERE COALESCE(ts_code, '') <> ''
              AND COALESCE(industry, '') <> ''
            """
        ).fetchdf()
    return frame[SECTOR_MAP_COLUMNS].drop_duplicates()


def _has_table(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    return table_name in tables
