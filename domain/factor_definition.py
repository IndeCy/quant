"""因子资产的强类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactorDefinition:
    """描述因子数据契约，不包含选股和持仓逻辑。"""

    factor_id: str
    name: str
    version: str
    direction: str
    as_of_policy: str
    source: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FactorDefinition":
        """从持久化配置构造并校验必要字段。"""
        required = ["factor_id", "name", "version", "direction", "as_of_policy", "source"]
        missing = [key for key in required if not str(payload.get(key) or "").strip()]
        if missing:
            raise ValueError(f"factor definition missing fields: {', '.join(missing)}")
        return cls(**{key: str(payload[key]).strip() for key in required})
