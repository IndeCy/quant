"""策略模板与策略实例测试。"""

from pathlib import Path

from runtime.repository import SystemRepository
from runtime.strategy_instance_catalog import register_builtin_strategy_instances
from runtime.strategy_templates import list_strategy_templates


def test_strategy_templates_include_factor_and_chain_templates() -> None:
    """系统应提供可复用策略模板，而不是只维护固定策略脚本。"""
    template_ids = [item["template_id"] for item in list_strategy_templates()]

    assert template_ids == ["factor_topn_monthly", "industry_chain_momentum"]


def test_strategy_instance_can_reference_factor_template(tmp_path: Path) -> None:
    """因子组合应能保存成可运行策略实例。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    instance = repository.upsert_strategy_instance(
        {
            "strategy_id": "quality_roa_ocf_v2",
            "name": "Quality ROA OCF V2",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": ["listed_3y", "exclude_st"],
            "factors": [
                {"factor_id": "roa", "weight": 0.6, "transform": "winsorize_zscore"},
                {"factor_id": "ocf_to_or", "weight": 0.4, "transform": "winsorize_zscore"},
            ],
            "construction": {"top_n": 20, "weighting": "equal_weight"},
            "risk_overlay": "vol_20_45_to_30",
            "benchmark": "510300",
        }
    )

    enabled = repository.list_strategy_instances(enabled_only=True)

    assert instance["enabled"] is True
    assert instance["factors"][0]["factor_id"] == "roa"
    assert enabled[0]["strategy_id"] == "quality_roa_ocf_v2"
    assert enabled[0]["construction"]["top_n"] == 20


def test_builtin_strategies_are_registered_as_instances(tmp_path: Path) -> None:
    """当前固定策略应兼容迁移为策略实例资产。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    register_builtin_strategy_instances(repository)

    instances = repository.list_strategy_instances(enabled_only=True)
    assert [item["strategy_id"] for item in instances] == ["mainline_chain_b", "quality_overlay"]
    assert instances[0]["template_id"] == "industry_chain_momentum"
    assert instances[1]["template_id"] == "factor_topn_monthly"


def test_strategy_instance_state_returns_empty_before_first_run(tmp_path: Path) -> None:
    """策略实例尚未运行时，状态查询应返回空持仓而不是报错。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    state = repository.load_strategy_instance_state("paper_test")

    assert state == {"strategy_id": "paper_test", "trade_date": None, "nav": None, "holdings": []}
