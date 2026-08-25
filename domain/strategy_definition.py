"""声明式策略资产定义。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class FactorReference:
    """策略对已登记因子的引用和显式权重。"""

    factor_id: str
    weight: float
    transform: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FactorReference":
        factor_id = str(payload.get("factor_id") or "").strip()
        transform = str(payload.get("transform") or "").strip()
        if not factor_id or not transform:
            raise ValueError("factor_id and transform are required")
        return cls(factor_id=factor_id, weight=float(payload.get("weight", 1.0)), transform=transform)

    def to_dict(self) -> dict[str, object]:
        return {"factor_id": self.factor_id, "weight": self.weight, "transform": self.transform}


@dataclass(frozen=True)
class StrategyDefinition:
    """策略、组合、风险和执行策略的不可变版本声明。"""

    strategy_id: str
    name: str
    version: str
    template_id: str
    status: str
    enabled: bool
    universe: str
    filters: tuple[str, ...]
    factors: tuple[FactorReference, ...]
    construction: dict[str, Any]
    risk_overlay: str
    benchmark: str
    adjust_policy: str
    execution_policy: str
    config: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StrategyDefinition":
        """加载并校验稳定策略契约。"""
        text_fields = [
            "strategy_id", "name", "version", "template_id", "status", "universe",
            "risk_overlay", "benchmark", "adjust_policy", "execution_policy",
        ]
        values = {key: str(payload.get(key) or "").strip() for key in text_fields}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ValueError(f"strategy definition missing fields: {', '.join(missing)}")
        if not SEMVER_PATTERN.fullmatch(values["version"]):
            raise ValueError(f"invalid strategy version: {values['version']}")
        if values["adjust_policy"] != "qfq":
            raise ValueError("production strategy adjust_policy must be qfq")
        factors = tuple(FactorReference.from_dict(item) for item in payload.get("factors", []))
        factor_ids = [item.factor_id for item in factors]
        if len(factor_ids) != len(set(factor_ids)):
            raise ValueError(f"duplicate factor in strategy {values['strategy_id']}")
        if any(not math.isfinite(item.weight) or item.weight < 0 for item in factors):
            raise ValueError("factor weight must be finite and non-negative")
        if factors and not math.isclose(sum(item.weight for item in factors), 1.0, abs_tol=1e-9):
            raise ValueError("factor weights must sum to 1")
        construction = dict(payload.get("construction") or {})
        if "top_n" in construction and int(construction["top_n"]) <= 0:
            raise ValueError("construction.top_n must be positive")
        return cls(
            **values,
            enabled=bool(payload.get("enabled", False)),
            filters=tuple(str(item) for item in payload.get("filters", [])),
            factors=factors,
            construction=construction,
            config=dict(payload.get("config") or {}),
        )

    def to_instance_payload(self) -> dict[str, Any]:
        """转换成现有策略实例仓库格式，保持 Runner 向后兼容。"""
        config = {
            **self.config,
            "definition_version": self.version,
            "adjust_policy": self.adjust_policy,
            "execution_policy": self.execution_policy,
        }
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "template_id": self.template_id,
            "status": self.status,
            "enabled": self.enabled,
            "universe": self.universe,
            "filters": list(self.filters),
            "factors": [item.to_dict() for item in self.factors],
            "construction": self.construction,
            "risk_overlay": self.risk_overlay,
            "benchmark": self.benchmark,
            "config": config,
        }
