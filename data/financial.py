"""
财务数据 as-of 查询接口

该模块只定义低频多因子所需的财报可见性边界，不实现具体因子。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


REQUIRED_FINANCIAL_COLUMNS = [
    "symbol",
    "report_period",
    "publish_date",
    "statement_type",
    "field_name",
    "field_value",
    "source",
]


@dataclass(frozen=True)
class FinancialRecord:
    """一条标准财务字段记录。"""

    symbol: str
    report_period: pd.Timestamp
    publish_date: pd.Timestamp
    statement_type: str
    field_name: str
    field_value: float
    source: str = ""


class FinancialStatementStore:
    """本地财务数据 as-of 查询存储。"""

    def __init__(self, records: pd.DataFrame):
        self.records = self._normalize_records(records)

    @classmethod
    def from_records(cls, records: Iterable[dict]) -> "FinancialStatementStore":
        """从 dict 列表构造财务数据存储，便于测试和后续数据源接入。"""
        return cls(pd.DataFrame(list(records)))

    def _normalize_records(self, records: pd.DataFrame) -> pd.DataFrame:
        """统一字段、日期和排序，确保 as-of 查询稳定。"""
        missing = [column for column in REQUIRED_FINANCIAL_COLUMNS if column not in records.columns]
        if missing:
            raise ValueError(f"缺少财务数据字段: {missing}")

        result = records.copy()
        result["report_period"] = pd.to_datetime(result["report_period"]).dt.normalize()
        result["publish_date"] = pd.to_datetime(result["publish_date"]).dt.normalize()
        result["field_value"] = pd.to_numeric(result["field_value"], errors="coerce")
        result = result.sort_values(["symbol", "field_name", "publish_date", "report_period"])
        return result

    def get_latest_report(
        self,
        symbol: str,
        trade_date: str | pd.Timestamp,
        fields: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """
        返回交易日当时已经披露的最新财务字段。

        核心约束：publish_date 必须小于等于 trade_date，避免财报未来函数。
        """
        current = pd.Timestamp(trade_date).normalize()
        visible = self.records[
            (self.records["symbol"] == symbol)
            & (self.records["publish_date"] <= current)
        ]
        if fields is not None:
            visible = visible[visible["field_name"].isin(list(fields))]
        if visible.empty:
            return visible.copy()

        visible = visible.sort_values(["field_name", "report_period", "publish_date"])
        latest_index = visible.groupby("field_name")["report_period"].idxmax()
        latest = visible.loc[latest_index].sort_values("field_name")
        return latest.reset_index(drop=True)

    def get_financial_snapshot(
        self,
        symbol: str,
        trade_date: str | pd.Timestamp,
        fields: Iterable[str] | None = None,
    ) -> dict[str, float]:
        """返回某交易日可见的最新财务字段快照。"""
        latest = self.get_latest_report(symbol, trade_date, fields=fields)
        return {
            str(row["field_name"]): row["field_value"]
            for _, row in latest.iterrows()
        }

    def get_financial_series(
        self,
        symbol: str,
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
        fields: Iterable[str] | None = None,
        as_of: bool = True,
    ) -> pd.DataFrame:
        """返回披露日区间内的财务记录，默认遵守 as-of 可见性。"""
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
        data = self.records[self.records["symbol"] == symbol]
        if fields is not None:
            data = data[data["field_name"].isin(list(fields))]
        date_column = "publish_date" if as_of else "report_period"
        data = data[(data[date_column] >= start) & (data[date_column] <= end)]
        return data.reset_index(drop=True)


class FinancialDataPortal:
    """
    因子层使用的财务数据门面。

    该门面只暴露 as-of 查询方法，不暴露底层 records，避免因子绕过披露日约束。
    """

    def __init__(self, store: FinancialStatementStore):
        self._store = store

    def get_latest_report(
        self,
        symbol: str,
        trade_date: str | pd.Timestamp,
        fields: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """返回交易日当时已经披露的最新财务字段。"""
        return self._store.get_latest_report(symbol, trade_date, fields=fields)

    def get_financial_snapshot(
        self,
        symbol: str,
        trade_date: str | pd.Timestamp,
        fields: Iterable[str] | None = None,
    ) -> dict[str, float]:
        """返回交易日当时已经披露的最新财务快照。"""
        return self._store.get_financial_snapshot(symbol, trade_date, fields=fields)

    def get_financial_series(
        self,
        symbol: str,
        start_date: str | pd.Timestamp,
        end_date: str | pd.Timestamp,
        fields: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """返回披露日口径的财务记录区间，禁止按报告期绕过 as-of。"""
        return self._store.get_financial_series(symbol, start_date, end_date, fields=fields, as_of=True)
