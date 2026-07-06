"""内置策略目录测试。"""

from pathlib import Path

from runtime.repository import SystemRepository
from runtime.strategy_catalog import (
    register_innovative_drug_observer_v0,
    register_builtin_strategies,
    register_mainline_chain_factor_v1,
    register_quality_alpha_v1,
)


def test_register_quality_alpha_v1_records_factor_composition(tmp_path: Path) -> None:
    """当前生产候选策略应登记为三因子等权组合。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_quality_alpha_v1(repository)

    definition = repository.load_strategy_definition("quality_overlay")
    assert definition is not None
    assert definition["name"] == "Quality Alpha V1"
    assert definition["config"]["top_n"] == 20
    assert [item["factor_id"] for item in definition["factors"]] == ["ocf_to_or", "roa", "roe"]
    assert round(sum(item["weight"] for item in definition["factors"]), 6) == 1.0


def test_register_mainline_chain_factor_v1_records_native_definition(tmp_path: Path) -> None:
    """主线链动原生策略应登记为因子组合产业链轮动。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_mainline_chain_factor_v1(repository)

    definition = repository.load_strategy_definition("mainline_chain_factor_v1")
    assert definition is not None
    assert definition["name"] == "主线链动因子 V1"
    assert definition["status"] == "shadow_live"
    assert definition["strategy_type"] == "factor_chain_rotation"
    assert definition["config"]["adjust_policy"] == "qfq"
    assert [item["factor_id"] for item in definition["factors"]] == [
        "mainline_chain_gate",
        "mainline_chain_strength_60d",
        "mainline_stock_momentum_120d",
        "mainline_stock_momentum_60d",
    ]


def test_register_innovative_drug_observer_v0_records_observation_definition(tmp_path: Path) -> None:
    """创新药出海观察策略应登记为不可交易观察策略。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_innovative_drug_observer_v0(repository)

    definition = repository.load_strategy_definition("innovative_drug_globalization_observer_v0")
    assert definition is not None
    assert definition["name"] == "创新药出海观察策略 V0"
    assert definition["status"] == "research_observation"
    assert definition["strategy_type"] == "opportunity_observer"
    assert definition["config"]["trade_policy"] == "observation_only"


def test_register_builtin_strategies_exposes_quality_and_mainline(tmp_path: Path) -> None:
    """内置策略目录应同时暴露生产、影子和观察策略。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_builtin_strategies(repository)

    strategy_ids = [item["strategy_id"] for item in repository.list_strategies()]
    assert strategy_ids == ["innovative_drug_globalization_observer_v0", "mainline_chain_factor_v1", "quality_overlay"]
