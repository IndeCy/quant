"""内置策略实例登记。"""

from __future__ import annotations

from runtime.repository import SystemRepository
from runtime.strategy_definition_loader import load_strategy_definitions


def register_builtin_strategy_instances(repository: SystemRepository) -> None:
    """从版本化声明把内置策略登记为可运行实例。"""
    repository.delete_strategy_artifacts("mainline_chain_b")
    for definition in load_strategy_definitions():
        repository.upsert_strategy_instance(definition.to_instance_payload())
