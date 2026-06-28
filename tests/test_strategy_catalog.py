"""内置策略目录测试。"""

from pathlib import Path

from runtime.repository import SystemRepository
from runtime.strategy_catalog import register_quality_alpha_v1


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
