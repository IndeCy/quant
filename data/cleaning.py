"""
基础日频行情清洗

Phase 1 只做可信回测必需的轻量清洗：日期、排序、去重、缺失和异常价格打标。
"""

from __future__ import annotations

import pandas as pd

from data.schema import (
    CLOSE,
    HIGH,
    IS_SUSPENDED,
    LOW,
    OPEN,
    PRICE_COLUMNS,
    VOLUME,
    ordered_daily_bar_columns,
    standardize_daily_bar_schema,
)


def clean_daily_bars(df: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame:
    """
    清洗日K数据并返回统一字段。

    不默认删除缺价或异常价格行，而是打标，避免把停牌和数据质量问题悄悄吞掉。
    """
    result = standardize_daily_bar_schema(df, symbol=symbol)
    if result.empty:
        return result

    # 日期索引去重时保留最后一条，适配缓存重复刷新后的覆盖语义。
    result = result[~result.index.duplicated(keep="last")].sort_index()

    missing_columns = [column for column in PRICE_COLUMNS if column not in result.columns]
    if missing_columns:
        raise ValueError(f"缺少必要价格字段: {missing_columns}")

    result["has_missing_price"] = result[PRICE_COLUMNS].isna().any(axis=1)
    result["has_invalid_price"] = (result[PRICE_COLUMNS] <= 0).any(axis=1)

    if IS_SUSPENDED not in result.columns:
        result[IS_SUSPENDED] = False
    result[IS_SUSPENDED] = result[IS_SUSPENDED].fillna(False).astype(bool)
    if VOLUME in result.columns:
        # 成交量为0常见于停牌或不可交易日，保守标记为停牌。
        result.loc[result[VOLUME].fillna(0) <= 0, IS_SUSPENDED] = True

    # high/low 与 open/close 的基本一致性检查，先打标不删除。
    result["has_inconsistent_price"] = (
        (result[HIGH] < result[[OPEN, CLOSE, LOW]].max(axis=1))
        | (result[LOW] > result[[OPEN, CLOSE, HIGH]].min(axis=1))
    )

    return result[ordered_daily_bar_columns(result.columns)]
