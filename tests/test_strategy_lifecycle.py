"""策略生命周期状态机测试。"""

from pathlib import Path

import pytest

from runtime.repository import SystemRepository
from runtime.strategy_lifecycle import StrategyLifecycleError


def _seed_instance(repository: SystemRepository, status: str = "draft", enabled: bool = False) -> None:
    """创建最小策略实例。"""
    repository.upsert_strategy_instance(
        {
            "strategy_id": "quality_test",
            "name": "Quality Test",
            "template_id": "factor_topn_monthly",
            "status": status,
            "enabled": enabled,
            "universe": "all_a",
            "filters": [],
            "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "zscore"}],
            "construction": {"top_n": 20, "weighting": "equal_weight"},
            "benchmark": "510300",
        }
    )


def _register_factor_contract(repository: SystemRepository) -> None:
    repository.upsert_factor_contract(
        {
            "factor_id": "roa",
            "name": "ROA",
            "category": "quality",
            "direction": "higher_is_better",
            "source": "fina_indicator",
            "frequency": "annual",
            "value_type": "numeric",
            "as_of_policy": "financial_announcement",
            "as_of_field": "f_ann_date",
            "effective_date_field": "trade_date",
            "input_datasets": ["fina_indicator_duckdb"],
            "input_fields": ["roa"],
            "output_fields": ["trade_date", "symbol", "factor_value"],
            "status": "active",
        }
    )


def test_strategy_lifecycle_allows_valid_transition(tmp_path: Path) -> None:
    """draft -> research -> paper 应按状态机流转。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    _register_factor_contract(repository)
    _seed_instance(repository, status="draft", enabled=False)

    research = repository.transition_strategy_instance_status("quality_test", "research")
    paper = repository.transition_strategy_instance_status("quality_test", "paper", enable=True)

    assert research["status"] == "research"
    assert research["enabled"] is False
    assert paper["status"] == "paper"
    assert paper["enabled"] is True


def test_strategy_lifecycle_rejects_invalid_transition(tmp_path: Path) -> None:
    """draft 不能直接跳到 live。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    _register_factor_contract(repository)
    _seed_instance(repository, status="draft", enabled=False)

    with pytest.raises(StrategyLifecycleError, match="invalid transition"):
        repository.transition_strategy_instance_status("quality_test", "live")


def test_strategy_lifecycle_requires_factor_contract_before_run_state(tmp_path: Path) -> None:
    """进入 paper 前必须确认策略因子都有契约。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    _seed_instance(repository, status="research", enabled=False)

    with pytest.raises(StrategyLifecycleError, match="missing factor contracts"):
        repository.transition_strategy_instance_status("quality_test", "paper", enable=True)


def test_list_runnable_strategy_instances_filters_lifecycle_status(tmp_path: Path) -> None:
    """draft/research/retired 即使 enabled=True 也不能进入每日批处理。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
    _register_factor_contract(repository)
    for strategy_id, status in [
        ("draft_on", "draft"),
        ("research_on", "research"),
        ("paper_on", "paper"),
        ("shadow_on", "shadow_live"),
        ("retired_on", "retired"),
    ]:
        repository.upsert_strategy_instance(
            {
                "strategy_id": strategy_id,
                "name": strategy_id,
                "template_id": "factor_topn_monthly",
                "status": status,
                "enabled": True,
                "factors": [{"factor_id": "roa", "weight": 1.0}],
                "construction": {"top_n": 2},
                "benchmark": "510300",
            }
        )

    runnable = repository.list_runnable_strategy_instances()

    assert [item["strategy_id"] for item in runnable] == ["paper_on", "shadow_on"]
