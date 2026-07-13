"""声明式策略资产测试。"""

from pathlib import Path

import pytest

from domain.strategy_definition import StrategyDefinition
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_definition_loader import load_strategy_definitions
from runtime.strategy_instance_catalog import register_builtin_strategy_instances


def test_builtin_strategy_definitions_are_versioned_and_valid() -> None:
    """所有内置策略都必须声明版本、复权和执行口径。"""
    definitions = load_strategy_definitions()

    assert {item.strategy_id for item in definitions} == {
        "innovative_drug_globalization_observer_v0",
        "mainline_chain_factor_v1",
        "quality_overlay",
    }
    assert all(item.version for item in definitions)
    assert all(item.adjust_policy == "qfq" for item in definitions)
    assert all(item.execution_policy for item in definitions)


def test_strategy_definition_rejects_duplicate_factors() -> None:
    """重复因子会造成隐式加权，声明加载时必须拒绝。"""
    payload = {
        "strategy_id": "demo_v1",
        "name": "Demo",
        "version": "1.0.0",
        "template_id": "factor_topn_monthly",
        "status": "draft",
        "enabled": False,
        "universe": "all_a",
        "filters": [],
        "factors": [
            {"factor_id": "roe", "weight": 0.5, "transform": "zscore"},
            {"factor_id": "roe", "weight": 0.5, "transform": "zscore"},
        ],
        "construction": {"top_n": 20},
        "risk_overlay": "none",
        "benchmark": "510300",
        "adjust_policy": "qfq",
        "execution_policy": "m0_t1",
        "config": {},
    }

    with pytest.raises(ValueError, match="duplicate factor"):
        StrategyDefinition.from_dict(payload)


def test_builtin_registry_is_loaded_from_definition_files(tmp_path: Path) -> None:
    """运行实例注册必须保留声明版本，历史结果才能追溯。"""
    paths = RuntimePaths(tmp_path)
    repository = SystemRepository(paths.system_state_path)

    register_builtin_strategy_instances(repository)

    quality = repository.load_strategy_instance("quality_overlay")
    assert quality["factors"][0]["factor_id"] == "roe"
    assert quality["construction"]["top_n"] == 20
    assert quality["config"]["definition_version"] == "1.0.0"
    assert quality["config"]["execution_policy"] == "m0_t1"
