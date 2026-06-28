"""
复权口径定义

统一约束行情缓存、DataManager 和回测报告使用的复权语义。
"""

from __future__ import annotations

from enum import Enum


class AdjustType(str, Enum):
    """A股常用复权口径。"""

    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


ADJUST_ALIASES = {
    "": AdjustType.NONE,
    "none": AdjustType.NONE,
    "不复权": AdjustType.NONE,
    "raw": AdjustType.NONE,
    "qfq": AdjustType.QFQ,
    "前复权": AdjustType.QFQ,
    "forward": AdjustType.QFQ,
    "hfq": AdjustType.HFQ,
    "后复权": AdjustType.HFQ,
    "backward": AdjustType.HFQ,
}

DEFAULT_SIGNAL_ADJUST = AdjustType.QFQ
DEFAULT_EXECUTION_ADJUST = AdjustType.NONE


def normalize_adjust(value: str | AdjustType | None) -> AdjustType:
    """归一化复权口径，非法值直接报错，避免隐式混用。"""
    if isinstance(value, AdjustType):
        return value
    key = "" if value is None else str(value).strip().lower()
    if key in ADJUST_ALIASES:
        return ADJUST_ALIASES[key]
    raise ValueError(f"未知复权口径: {value}，仅支持 none/qfq/hfq")


def normalize_adjust_value(value: str | AdjustType | None) -> str:
    """返回可用于缓存 key 和 DataFrame attrs 的复权字符串。"""
    return normalize_adjust(value).value
