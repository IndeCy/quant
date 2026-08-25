"""面向策略和研究的统一只读数据入口。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

from data.dataset_contract import DatasetBinding
from data.financial import FinancialDataPortal
from data.market_snapshot import FundMarketDataSnapshot, MarketDataSnapshot


FinancialPortalLoader = Callable[[], FinancialDataPortal]


class QuantDataSnapshot:
    """把统一接口绑定到一个明确的 as-of 日期和数据版本。"""

    def __init__(
        self,
        *,
        as_of_date: str,
        stock_market: MarketDataSnapshot,
        fund_market: FundMarketDataSnapshot,
        financial_portal: FinancialDataPortal | FinancialPortalLoader,
        datasets: Iterable[DatasetBinding] = (),
    ) -> None:
        self.as_of_date = _normalize_date(as_of_date, "as_of_date")
        if stock_market.as_of_date != self.as_of_date or fund_market.as_of_date != self.as_of_date:
            raise ValueError("行情快照日期必须与统一数据快照一致")
        self.stock_market = stock_market
        self.fund_market = fund_market
        self._financial_source = financial_portal
        self._financial_cache: FinancialDataPortal | None = None
        bindings = list(datasets)
        self._datasets = {item.contract.dataset_id: item for item in bindings}
        if len(self._datasets) != len(bindings):
            raise ValueError("dataset_id 必须唯一")
        self.snapshot_id = _snapshot_identity(
            self.as_of_date,
            stock_market.snapshot_id,
            fund_market.snapshot_id,
            self._datasets,
        )

    def list_datasets(self) -> list[dict[str, Any]]:
        """列出可通过通用表接口读取的数据集。"""
        return [
            {
                "dataset_id": binding.contract.dataset_id,
                "table_name": binding.contract.table_name,
                "date_field": binding.contract.date_field or "",
                "symbol_field": binding.contract.symbol_field or "",
                "provider": binding.contract.provider,
                "frequency": binding.contract.frequency,
                "description": binding.contract.description,
                "available": binding.path.exists(),
            }
            for binding in sorted(self._datasets.values(), key=lambda item: item.contract.dataset_id)
        ]

    def stock_bars(self, symbol: str, start_date: str | None = None) -> pd.DataFrame:
        """读取前复权 A 股日线，继续复用生产行情快照。"""
        result = self.stock_market.load_daily_bars(symbol, start_date=start_date)
        return _annotate(result, self, "market.stock_daily")

    def fund_bars(self, symbol: str, start_date: str | None = None) -> pd.DataFrame:
        """读取前复权 ETF/基金日线，继续复用基金行情快照。"""
        result = self.fund_market.load_daily_bars(symbol, start_date=start_date)
        return _annotate(result, self, "market.fund_daily")

    def financial_snapshot(
        self,
        symbol: str,
        fields: Iterable[str] | None = None,
    ) -> dict[str, float]:
        """读取快照日当时可见的最新财务字段，禁止绕过公告日。"""
        return self._financial().get_financial_snapshot(symbol, self.as_of_date, fields=fields)

    def financial_series(
        self,
        symbol: str,
        start_date: str,
        fields: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """读取公告日区间内的财务长表。"""
        start = _normalize_date(start_date, "start_date")
        if start > self.as_of_date:
            raise ValueError("start_date 不能晚于快照 as_of_date")
        result = self._financial().get_financial_series(symbol, start, self.as_of_date, fields=fields)
        return _annotate(result, self, "financial.asof")

    def load_dataset(
        self,
        dataset_id: str,
        *,
        start_date: str | None = None,
        symbols: Iterable[str] | None = None,
        columns: Iterable[str] | None = None,
        latest_only: bool = False,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """读取扩展数据集，并在 SQL 层强制截断到快照日。

        对带日期的大表，调用方必须给出 start_date 或 latest_only，避免策略误读
        全量历史。静态映射表不受此限制。
        """
        binding = self._binding(dataset_id)
        contract = binding.contract
        if not binding.path.exists():
            raise FileNotFoundError(f"数据集文件不存在: {binding.path}")
        if contract.date_field and not latest_only and start_date is None:
            raise ValueError("带日期的数据集必须指定 start_date 或 latest_only=True")
        start = _normalize_date(start_date, "start_date") if start_date else None
        if start and start > self.as_of_date:
            raise ValueError("start_date 不能晚于快照 as_of_date")
        normalized_limit = _normalize_limit(limit)

        import duckdb

        with duckdb.connect(str(binding.path), read_only=True) as con:
            available = _table_columns(con, contract.table_name)
            _validate_contract_columns(contract, available)
            selected = _select_columns(columns, available)
            sql, params = _dataset_query(
                contract=contract,
                selected=selected,
                start_date=start,
                as_of_date=self.as_of_date,
                symbols=symbols,
                latest_only=latest_only,
                limit=normalized_limit,
            )
            result = con.execute(sql, params).fetchdf()
        return _annotate(result, self, dataset_id)

    def coverage(self, dataset_id: str) -> dict[str, Any]:
        """读取表级覆盖范围，不加载业务明细。"""
        binding = self._binding(dataset_id)
        contract = binding.contract
        if not binding.path.exists():
            return {"dataset_id": dataset_id, "available": False, "row_count": 0}
        import duckdb

        with duckdb.connect(str(binding.path), read_only=True) as con:
            available = _table_columns(con, contract.table_name)
            _validate_contract_columns(contract, available)
            if contract.date_field:
                row = con.execute(
                    f'SELECT COUNT(*), MIN("{contract.date_field}"), MAX("{contract.date_field}") '
                    f'FROM "{contract.table_name}" WHERE "{contract.date_field}" <= ?',
                    [self.as_of_date],
                ).fetchone()
                minimum, maximum = str(row[1] or ""), str(row[2] or "")
            else:
                row = con.execute(f'SELECT COUNT(*) FROM "{contract.table_name}"').fetchone()
                minimum, maximum = "", ""
        return {
            "dataset_id": dataset_id,
            "available": True,
            "row_count": int(row[0]),
            "start_date": minimum,
            "end_date": maximum,
            "as_of_date": self.as_of_date,
        }

    def _binding(self, dataset_id: str) -> DatasetBinding:
        try:
            return self._datasets[dataset_id]
        except KeyError as exc:
            raise KeyError(f"未注册数据集: {dataset_id}") from exc

    def _financial(self) -> FinancialDataPortal:
        if self._financial_cache is None:
            source = self._financial_source
            self._financial_cache = source() if callable(source) else source
        return self._financial_cache


def _dataset_query(
    *,
    contract: Any,
    selected: list[str],
    start_date: str | None,
    as_of_date: str,
    symbols: Iterable[str] | None,
    latest_only: bool,
    limit: int | None,
) -> tuple[str, list[Any]]:
    columns_sql = ", ".join(f'"{column}"' for column in selected)
    table_sql = f'"{contract.table_name}"'
    where: list[str] = []
    params: list[Any] = []
    if contract.date_field:
        where.append(f'"{contract.date_field}" <= ?')
        params.append(as_of_date)
        if start_date:
            where.append(f'"{contract.date_field}" >= ?')
            params.append(start_date)
        if latest_only:
            where.append(
                f'"{contract.date_field}" = (SELECT MAX("{contract.date_field}") '
                f'FROM {table_sql} WHERE "{contract.date_field}" <= ?)'
            )
            params.append(as_of_date)
    symbol_list = sorted({str(symbol) for symbol in symbols or []})
    if symbol_list:
        if not contract.symbol_field:
            raise ValueError(f"数据集 {contract.dataset_id} 不支持 symbols 过滤")
        placeholders = ", ".join("?" for _ in symbol_list)
        where.append(f'"{contract.symbol_field}" IN ({placeholders})')
        params.extend(symbol_list)
    sql = f"SELECT {columns_sql} FROM {table_sql}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = [column for column in [contract.date_field, *contract.primary_key] if column and column in selected]
    if order:
        sql += " ORDER BY " + ", ".join(f'"{column}"' for column in dict.fromkeys(order))
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return sql, params


def _table_columns(con: Any, table_name: str) -> list[str]:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    if table_name not in tables:
        raise ValueError(f"DuckDB 缺少契约表: {table_name}")
    return [str(row[0]) for row in con.execute(f'DESCRIBE "{table_name}"').fetchall()]


def _validate_contract_columns(contract: Any, available: list[str]) -> None:
    required = [*contract.primary_key]
    if contract.date_field:
        required.append(contract.date_field)
    if contract.symbol_field:
        required.append(contract.symbol_field)
    missing = [column for column in dict.fromkeys(required) if column not in available]
    if missing:
        raise ValueError(f"数据集 {contract.dataset_id} 缺少契约字段: {missing}")


def _select_columns(columns: Iterable[str] | None, available: list[str]) -> list[str]:
    selected = list(columns) if columns is not None else list(available)
    if not selected:
        raise ValueError("columns 不能为空")
    missing = [str(column) for column in selected if str(column) not in available]
    if missing:
        raise ValueError(f"请求了不存在的字段: {missing}")
    return [str(column) for column in selected]


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    value = int(limit)
    if value <= 0 or value > 1_000_000:
        raise ValueError("limit 必须在 1 到 1000000 之间")
    return value


def _annotate(frame: pd.DataFrame, snapshot: QuantDataSnapshot, dataset_id: str) -> pd.DataFrame:
    frame.attrs["dataset_id"] = dataset_id
    frame.attrs["snapshot_id"] = snapshot.snapshot_id
    frame.attrs["as_of_date"] = snapshot.as_of_date
    return frame


def _snapshot_identity(
    as_of_date: str,
    stock_id: str,
    fund_id: str,
    datasets: Mapping[str, DatasetBinding],
) -> str:
    records = [as_of_date, stock_id, fund_id]
    for dataset_id, binding in sorted(datasets.items()):
        path = binding.path
        if path.exists():
            stat = path.stat()
            identity = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
        else:
            identity = f"{path}:missing"
        records.append(f"{dataset_id}:{identity}")
    return sha256("\n".join(records).encode("utf-8")).hexdigest()[:20]


def _normalize_date(value: str, field_name: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"{field_name} 必须是 YYYYMMDD")
    return normalized
