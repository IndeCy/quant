"""内置策略目录测试。"""

from pathlib import Path

from runtime.repository import SystemRepository
from runtime.strategy_catalog import (
    register_global_defensive_equal_v1,
    register_innovative_drug_observer_v0,
    register_builtin_strategies,
    register_mainline_chain_factor_v1,
    register_quality_alpha_v1,
    register_quality_balanced_value_v1,
    register_quality_defensive_assets_v2,
    register_quality_value_lowvol_v0,
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


def test_register_quality_value_lowvol_v0_records_five_factor_contract(tmp_path: Path) -> None:
    """防御型 Quality 策略必须登记五因子和公司行为校验口径。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_quality_alpha_v1(repository)
    register_quality_value_lowvol_v0(repository)

    definition = repository.load_strategy_definition("quality_value_lowvol_v0")
    assert definition is not None
    assert definition["status"] == "retired"
    assert [item["factor_id"] for item in definition["factors"]] == [
        "book_yield",
        "earnings_yield",
        "low_volatility_60d",
        "ocf_to_or",
        "roa",
    ]
    earnings = repository.load_factor_contract("earnings_yield")
    assert earnings is not None
    assert earnings["as_of_field"] == "f_ann_date"
    assert earnings["validation"]["corporate_action_consistent"] is True


def test_register_quality_balanced_value_v1_records_shadow_contract(tmp_path: Path) -> None:
    """新候选必须明确Paper范围和冻结的80/10/10因子结构。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_quality_alpha_v1(repository)
    register_quality_value_lowvol_v0(repository)
    register_quality_balanced_value_v1(repository)

    definition = repository.load_strategy_definition("quality_balanced_value_v1")
    assert definition is not None
    assert definition["status"] == "shadow_live"
    assert definition["config"]["deployment_scope"] == "forward_paper_only"
    weights = {item["factor_id"]: item["weight"] for item in definition["factors"]}
    assert weights["earnings_yield"] == 0.10
    assert weights["book_yield"] == 0.10
    assert round(sum(weights.values()), 10) == 1.0


def test_register_quality_defensive_assets_v2_records_frozen_portfolio(tmp_path: Path) -> None:
    """长期Paper目录必须显示V2身份与核心风险预算，不能复用已拒绝V1。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    register_quality_alpha_v1(repository)
    register_quality_value_lowvol_v0(repository)
    register_quality_defensive_assets_v2(repository)

    definition = repository.load_strategy_definition(
        "quality_defensive_assets_core_scoped_70_15_15_v2"
    )
    assert definition is not None
    assert definition["status"] == "paper"
    assert definition["config"]["allocation"]["quality_core"] == 0.70
    assert definition["config"]["research_fingerprint"].endswith("_v2")


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


def test_register_global_defensive_equal_v1_is_observation_only(tmp_path: Path) -> None:
    """通过研究的三资产策略只登记观察身份，不能创建订单。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_global_defensive_equal_v1(repository)

    definition = repository.load_strategy_definition("global_defensive_equal_v1")
    assert definition is not None
    assert definition["status"] == "research_observation"
    assert definition["strategy_type"] == "fixed_allocation_observer"
    assert definition["config"]["trade_policy"] == "observation_only"
    assert sum(definition["config"]["allocation"].values()) == 1.0


def test_register_builtin_strategies_exposes_quality_and_mainline(tmp_path: Path) -> None:
    """内置策略目录应同时暴露生产、影子和观察策略。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_builtin_strategies(repository)

    strategy_ids = [item["strategy_id"] for item in repository.list_strategies()]
    assert strategy_ids == [
        "global_defensive_equal_v1",
        "innovative_drug_globalization_observer_v0",
        "mainline_chain_factor_v1",
        "quality_balanced_value_v1",
        "quality_defensive_assets_core_scoped_70_15_15_v2",
        "quality_overlay",
        "quality_value_lowvol_v0",
    ]
