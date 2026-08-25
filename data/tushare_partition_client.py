"""Tushare 按分区查询的最薄适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class TusharePartitionRequest:
    """一个已按官方文档确认的 Tushare 分区请求。"""

    endpoint: str
    partition_parameter: str
    fields: tuple[str, ...]
    static_parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in [self.endpoint, self.partition_parameter, *self.fields]:
            if not str(name).replace("_", "").isalnum():
                raise ValueError(f"非法 Tushare 标识符: {name}")
        if not self.fields:
            raise ValueError("fields 不能为空")


class TusharePartitionClient:
    """使用一个完整日期/公告日分区调用 Tushare。"""

    def __init__(self, token: str, request: TusharePartitionRequest, timeout: int = 30) -> None:
        if not token.strip():
            raise ValueError("TUSHARE_TOKEN 不能为空")
        import tushare as ts

        self.request = request
        self._pro = ts.pro_api(token, timeout=timeout)

    def fetch_partition(self, partition: str) -> pd.DataFrame:
        """按契约字段读取单个完整分区。"""
        parameters = dict(self.request.static_parameters)
        parameters[self.request.partition_parameter] = partition
        return self._pro.query(
            self.request.endpoint,
            fields=",".join(self.request.fields),
            **parameters,
        )
