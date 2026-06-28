"""
A股低频回测交易日历

默认使用内置 A 股真实休市日兜底，仍支持传入实际行情日期作为自定义交易日集合。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


DateLike = date | datetime | str | pd.Timestamp


# 覆盖近年常用回测和当前开发窗口的官方休市日。后续可通过 CSV 缓存扩展更长历史。
ASHARE_HOLIDAYS = {
    # 2023
    "2023-01-02",
    "2023-01-23", "2023-01-24", "2023-01-25", "2023-01-26", "2023-01-27",
    "2023-04-05",
    "2023-05-01", "2023-05-02", "2023-05-03",
    "2023-06-22", "2023-06-23",
    "2023-09-29",
    "2023-10-02", "2023-10-03", "2023-10-04", "2023-10-05", "2023-10-06",
    # 2024
    "2024-01-01",
    "2024-02-09", "2024-02-12", "2024-02-13", "2024-02-14",
    "2024-02-15", "2024-02-16",
    "2024-04-04", "2024-04-05",
    "2024-05-01", "2024-05-02", "2024-05-03",
    "2024-06-10",
    "2024-09-16", "2024-09-17",
    "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-07",
    # 2025
    "2025-01-01",
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-03", "2025-02-04",
    "2025-04-04",
    "2025-05-01", "2025-05-02", "2025-05-05",
    "2025-06-02",
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",
    # 2026
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-04-06",
    "2026-05-01",
    "2026-06-19",
    "2026-09-25",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",
}


def _normalize(value: DateLike) -> pd.Timestamp:
    """统一把日期归一到当天 00:00，避免时分秒影响交易日判断。"""
    return pd.Timestamp(value).normalize()


class TradingCalendar:
    """统一交易日历接口，供数据层和回测引擎共同使用。"""

    def __init__(
        self,
        trading_days: Iterable[DateLike] | None = None,
        holidays: Iterable[DateLike] | None = None,
    ):
        self._custom_days = None
        if trading_days is not None:
            self._custom_days = sorted({_normalize(day) for day in trading_days})
            self._custom_day_set = set(self._custom_days)
        else:
            self._custom_day_set = set()
        holiday_source = holidays if holidays is not None else ASHARE_HOLIDAYS
        self._holiday_set = {_normalize(day) for day in holiday_source}

    @classmethod
    def from_csv(cls, path: str | Path, column: str = "trade_date") -> "TradingCalendar":
        """从本地 CSV 载入真实交易日，作为外部数据源缓存接口。"""
        df = pd.read_csv(path)
        if column not in df.columns:
            raise ValueError(f"交易日历文件缺少字段: {column}")
        return cls(trading_days=pd.to_datetime(df[column]))

    def to_csv(self, path: str | Path, start_date: DateLike, end_date: DateLike) -> None:
        """将指定区间交易日写入本地 CSV 缓存。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({"trade_date": [day.date().isoformat() for day in self.trading_days(start_date, end_date)]})
        df.to_csv(target, index=False)

    def is_trading_day(self, day: DateLike) -> bool:
        """判断某天是否交易日。"""
        current = _normalize(day)
        if self._custom_days is not None:
            return current in self._custom_day_set
        return current.weekday() < 5 and current not in self._holiday_set

    def trading_days(self, start_date: DateLike, end_date: DateLike) -> list[pd.Timestamp]:
        """获取闭区间内所有交易日。"""
        start = _normalize(start_date)
        end = _normalize(end_date)
        if start > end:
            return []
        if self._custom_days is not None:
            return [day for day in self._custom_days if start <= day <= end]
        return [day for day in pd.bdate_range(start, end) if self.is_trading_day(day)]

    def next_trading_day(self, day: DateLike, offset: int = 1) -> pd.Timestamp | None:
        """
        获取后续第 offset 个交易日。

        offset=1 表示下一个交易日；若自定义日历中不存在后续日期，则返回 None。
        """
        if offset < 1:
            raise ValueError("offset 必须大于等于1")

        current = _normalize(day)
        if self._custom_days is not None:
            later_days = [candidate for candidate in self._custom_days if candidate > current]
            if len(later_days) < offset:
                return None
            return later_days[offset - 1]

        found = 0
        candidate = current
        while found < offset:
            candidate += timedelta(days=1)
            if self.is_trading_day(candidate):
                found += 1
        return candidate
