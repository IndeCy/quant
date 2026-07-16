"""生产策略统一行情快照门面。

快照把历史基线、每日增量、as-of 日期和复权口径绑定为一个可追溯数据版本。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pandas as pd

from data.adjustment import AdjustType, normalize_adjust
from data.cleaning import clean_daily_bars
from data.live_market_view import open_live_market_connection


@dataclass(frozen=True)
class MarketDataSnapshot:
    """某个交易日可见的只读行情快照。"""

    snapshot_id: str
    as_of_date: str
    lookback_start: str
    adjust_policy: AdjustType
    base_path: Path
    increment_path: Path

    def connect(self):
        """打开独立只读内存连接，调用方负责关闭。"""
        return open_live_market_connection(
            self.base_path,
            self.increment_path,
            lookback_start=self.lookback_start,
            as_of_date=self.as_of_date,
        )

    def load_daily_bars(
        self,
        symbol: str,
        start_date: str | None = None,
    ) -> pd.DataFrame:
        """读取单标的统一 schema 日线，绝不返回快照日之后的数据。"""
        start = _normalize_date(start_date or self.lookback_start, "start_date")
        if start > self.as_of_date:
            raise ValueError("start_date 不能晚于快照 as_of_date")
        price_columns = _price_columns(self.adjust_policy)
        query = f"""
            SELECT
                d.trade_date,
                d.ts_code AS code,
                d.ts_code AS symbol,
                {price_columns['open']} AS open,
                {price_columns['high']} AS high,
                {price_columns['low']} AS low,
                {price_columns['close']} AS close,
                d.vol AS volume,
                d.amount AS amount,
                COALESCE(d.vol, 0) <= 0 AS is_suspended,
                FALSE AS limit_up,
                FALSE AS limit_down,
                a.adj_factor
            FROM daily d
            JOIN daily_adj_cache a
              ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
            WHERE d.ts_code = ? AND d.trade_date BETWEEN ? AND ?
            ORDER BY d.trade_date
        """
        con = self.connect()
        try:
            frame = con.execute(query, [symbol, start, self.as_of_date]).fetchdf()
        finally:
            con.close()
        result = clean_daily_bars(frame, symbol=symbol)
        result.attrs["adjust"] = self.adjust_policy.value
        result.attrs["source"] = "market_data_snapshot"
        result.attrs["snapshot_id"] = self.snapshot_id
        result.attrs["as_of_date"] = self.as_of_date
        return result


def create_market_snapshot(
    base_path: str | Path,
    increment_path: str | Path,
    as_of_date: str,
    *,
    lookback_start: str = "20140701",
    adjust_policy: str | AdjustType = AdjustType.QFQ,
) -> MarketDataSnapshot:
    """创建可复现行情快照；当前生产信号口径默认前复权。"""
    base = Path(base_path).expanduser().resolve()
    increment = Path(increment_path).expanduser().resolve()
    if not base.exists():
        raise FileNotFoundError(f"历史基线库不存在: {base}")
    if not increment.exists():
        raise FileNotFoundError(f"增量行情库不存在: {increment}")
    normalized_as_of = _normalize_date(as_of_date, "as_of_date")
    normalized_start = _normalize_date(lookback_start, "lookback_start")
    if normalized_start > normalized_as_of:
        raise ValueError("lookback_start 不能晚于 as_of_date")
    adjust = normalize_adjust(adjust_policy)
    identity = "|".join(
        [
            _file_identity(base),
            _file_identity(increment),
            normalized_as_of,
            normalized_start,
            adjust.value,
        ]
    )
    return MarketDataSnapshot(
        snapshot_id=sha256(identity.encode("utf-8")).hexdigest()[:20],
        as_of_date=normalized_as_of,
        lookback_start=normalized_start,
        adjust_policy=adjust,
        base_path=base,
        increment_path=increment,
    )


def _price_columns(adjust_policy: AdjustType) -> dict[str, str]:
    """把复权枚举映射到固定 SQL 列，禁止调用方注入列名。"""
    if adjust_policy == AdjustType.NONE:
        return {name: f"d.{name}" for name in ("open", "high", "low", "close")}
    suffix = adjust_policy.value
    return {name: f"a.{name}_{suffix}" for name in ("open", "high", "low", "close")}


def _file_identity(path: Path) -> str:
    """文件路径、大小和修改时间共同构成轻量数据版本。"""
    stat = path.stat()
    return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"


def _normalize_date(value: str, field_name: str) -> str:
    """统一 YYYYMMDD 日期输入。"""
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"{field_name} 必须是 YYYYMMDD")
    return normalized
