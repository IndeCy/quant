"""从版本化配置加载策略资产。"""

from __future__ import annotations

import json
from pathlib import Path

from domain.strategy_definition import StrategyDefinition


DEFAULT_STRATEGY_DIR = Path(__file__).resolve().parents[1] / "config" / "strategies"


def load_strategy_definitions(directory: str | Path = DEFAULT_STRATEGY_DIR) -> list[StrategyDefinition]:
    """加载全部 JSON 策略定义，并拒绝重复 strategy_id。"""
    base = Path(directory)
    definitions = [
        StrategyDefinition.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(base.glob("*.json"))
    ]
    strategy_ids = [item.strategy_id for item in definitions]
    if len(strategy_ids) != len(set(strategy_ids)):
        raise ValueError("duplicate strategy_id in strategy definitions")
    return definitions


def load_strategy_definition(
    strategy_id: str,
    directory: str | Path = DEFAULT_STRATEGY_DIR,
) -> StrategyDefinition:
    """按ID读取策略声明。"""
    for definition in load_strategy_definitions(directory):
        if definition.strategy_id == strategy_id:
            return definition
    raise KeyError(strategy_id)
