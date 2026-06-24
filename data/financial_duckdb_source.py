"""
DuckDB 财务数据源适配。

把 income/balancesheet/cashflow/fina_indicator/forecast/express 等本地
DuckDB 表转换成统一 FinancialDataPortal，并强制使用公告日 as-of。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from data.financial import FinancialDataPortal, FinancialStatementStore


class DuckDBFinancialDataSource:
    """本地 DuckDB 财务库适配器。"""

    def __init__(self, db_paths: dict[str, str | Path]):
        self.db_paths = {name: Path(path) for name, path in db_paths.items()}
        missing = [str(path) for path in self.db_paths.values() if not path.exists()]
        if missing:
            raise FileNotFoundError(f"财务 DuckDB 文件不存在: {missing}")

    def get_financial_portal(
        self,
        fields_by_statement: dict[str, Iterable[str]] | None = None,
    ) -> FinancialDataPortal:
        """构造 as-of 财务查询门面。"""
        frames = []
        for statement_type, path in self.db_paths.items():
            fields = list(fields_by_statement.get(statement_type, [])) if fields_by_statement else None
            frame = self._read_statement(path, statement_type, fields)
            if not frame.empty:
                frames.append(frame)
        records = pd.concat(frames, ignore_index=True) if frames else self._empty_records()
        return FinancialDataPortal(FinancialStatementStore(records))

    def _read_statement(self, path: Path, statement_type: str, fields: list[str] | None) -> pd.DataFrame:
        """读取单个财务库并转成长表。"""
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError("缺少 duckdb 依赖，请先安装: python -m pip install duckdb") from exc
        with duckdb.connect(str(path), read_only=True) as con:
            columns = [row[0] for row in con.execute("DESCRIBE default_table").fetchall()]
            publish_column = "f_ann_date" if "f_ann_date" in columns else "ann_date"
            value_fields = fields or [
                column
                for column in columns
                if column not in {"ts_code", "end_date", "ann_date", "f_ann_date", "report_type", "comp_type", "end_type", "update_flag"}
            ]
            available_fields = [field for field in value_fields if field in columns]
            if not available_fields:
                return self._empty_records()
            select_fields = ", ".join([f'"{field}"' for field in available_fields])
            wide = con.execute(
                f"""
                SELECT ts_code, end_date, {publish_column} AS publish_date, {select_fields}
                FROM default_table
                WHERE {publish_column} IS NOT NULL
                """
            ).fetchdf()
        if wide.empty:
            return self._empty_records()
        long = wide.melt(
            id_vars=["ts_code", "end_date", "publish_date"],
            value_vars=available_fields,
            var_name="field_name",
            value_name="field_value",
        )
        long = long.dropna(subset=["field_value"])
        return pd.DataFrame(
            {
                "symbol": long["ts_code"],
                "report_period": long["end_date"],
                "publish_date": long["publish_date"],
                "statement_type": statement_type,
                "field_name": long["field_name"],
                "field_value": long["field_value"],
                "source": f"duckdb:{path.name}",
            }
        )

    def _empty_records(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "symbol",
                "report_period",
                "publish_date",
                "statement_type",
                "field_name",
                "field_value",
                "source",
            ]
        )
