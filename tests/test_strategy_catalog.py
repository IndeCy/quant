"""内置策略目录测试。"""

from pathlib import Path

from runtime.repository import SystemRepository
from runtime.strategy_catalog import (
    register_builtin_strategies,
    register_mainline_chain_b,
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


def test_register_mainline_chain_b_records_shadow_live_definition(tmp_path: Path) -> None:
    """主线链动策略应登记为影子实盘观察策略，不挂接基本面因子。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_mainline_chain_b(repository)

    definition = repository.load_strategy_definition("mainline_chain_b")
    assert definition is not None
    assert definition["name"] == "主线链动策略"
    assert definition["status"] == "shadow_live"
    assert definition["strategy_type"] == "industry_chain_momentum"
    assert definition["config"]["mode"] == "multi_chain"
    assert definition["config"]["top_n"] == 5
    assert definition["config"]["momentum_windows"] == [60, 120]
    assert definition["config"]["chain_momentum_window"] == 60
    assert definition["config"]["entrypoint"] == "examples/post_close_mainline_chain_observer.py"
    assert definition["factors"] == []


def test_register_builtin_strategies_exposes_quality_and_mainline(tmp_path: Path) -> None:
    """内置策略目录应同时暴露 Quality 和主线链动。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_builtin_strategies(repository)

    strategy_ids = [item["strategy_id"] for item in repository.list_strategies()]
    assert strategy_ids == ["mainline_chain_b", "quality_overlay"]
