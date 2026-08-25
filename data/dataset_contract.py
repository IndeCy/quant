"""统一数据集契约。

契约只描述已经存在的数据表，不负责建表。数据库结构必须先通过版本化 migration
落地，增量写入器随后才允许使用，避免同步代码静默创建错误 Schema。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetContract:
    """策略可读取的数据集字段与时间边界。"""

    dataset_id: str
    table_name: str
    primary_key: tuple[str, ...]
    date_field: str | None = None
    symbol_field: str | None = None
    provider: str = ""
    frequency: str = ""
    description: str = ""
    write_columns: tuple[str, ...] = ()
    allow_empty_partition: bool = False

    def __post_init__(self) -> None:
        _validate_identifier(self.dataset_id, "dataset_id", allow_dot=True)
        _validate_identifier(self.table_name, "table_name")
        if not self.primary_key:
            raise ValueError("primary_key 不能为空")
        for column in self.primary_key:
            _validate_identifier(column, "primary_key")
        if self.date_field:
            _validate_identifier(self.date_field, "date_field")
        if self.symbol_field:
            _validate_identifier(self.symbol_field, "symbol_field")
        for column in self.write_columns:
            _validate_identifier(column, "write_columns")
        missing_keys = [column for column in self.primary_key if self.write_columns and column not in self.write_columns]
        if missing_keys:
            raise ValueError(f"write_columns 缺少主键字段: {missing_keys}")
        if self.write_columns and self.date_field and self.date_field not in self.write_columns:
            raise ValueError("write_columns 必须包含 date_field")


@dataclass(frozen=True)
class DatasetBinding:
    """把稳定数据集 ID 绑定到当前机器上的 DuckDB 文件。"""

    contract: DatasetContract
    path: Path

    def __init__(self, contract: DatasetContract, path: str | Path) -> None:
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "path", Path(path).expanduser().resolve())


def _validate_identifier(value: str, field_name: str, *, allow_dot: bool = False) -> None:
    """限制动态 SQL 标识符，实际查询值始终继续使用参数绑定。"""
    text = str(value)
    normalized = text.replace(".", "_") if allow_dot else text
    if not normalized or not normalized.replace("_", "").isalnum() or normalized[0].isdigit():
        raise ValueError(f"{field_name} 不是合法标识符: {value}")
