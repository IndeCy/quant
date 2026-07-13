"""Factor Registry V2 测试。"""

from pathlib import Path

import pytest

from runtime.repository import SystemRepository


def test_factor_contract_persists_as_of_and_data_dependencies(tmp_path: Path) -> None:
    """因子契约应保存 as-of、安全口径和数据依赖。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    saved = repository.upsert_factor_contract(
        {
            "factor_id": "roa",
            "name": "ROA",
            "category": "quality",
            "direction": "higher_is_better",
            "source": "fina_indicator",
            "description": "总资产收益率",
            "version": "v1",
            "status": "active",
            "frequency": "annual",
            "value_type": "numeric",
            "as_of_policy": "financial_announcement",
            "as_of_field": "f_ann_date",
            "effective_date_field": "trade_date",
            "lag_days": 0,
            "input_datasets": ["fina_indicator_duckdb"],
            "input_fields": ["ts_code", "end_date", "f_ann_date", "roa"],
            "output_fields": ["trade_date", "symbol", "factor_value"],
            "dependencies": [],
            "validation": {"winsorize": True, "zscore": True},
            "owner": "Codex",
        }
    )
    detail = repository.load_factor_contract("roa")

    assert saved["factor_id"] == "roa"
    assert detail is not None
    assert detail["as_of_field"] == "f_ann_date"
    assert detail["input_datasets"] == ["fina_indicator_duckdb"]
    assert detail["validation"]["zscore"] is True
    assert repository.load_factor_definition("roa")["config"]["as_of_field"] == "f_ann_date"


def test_financial_factor_contract_requires_as_of_field(tmp_path: Path) -> None:
    """财务数据因子没有 as-of 字段时不能进入正式契约。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    with pytest.raises(ValueError, match="as_of_field"):
        repository.upsert_factor_contract(
            {
                "factor_id": "roe",
                "name": "ROE",
                "category": "quality",
                "direction": "higher_is_better",
                "source": "fina_indicator",
                "frequency": "annual",
                "value_type": "numeric",
                "as_of_policy": "financial_announcement",
                "input_datasets": ["fina_indicator_duckdb"],
                "input_fields": ["roe"],
                "output_fields": ["trade_date", "symbol", "factor_value"],
            }
        )


def test_strategy_factor_contract_validation_reports_missing_contracts(tmp_path: Path) -> None:
    """策略实例应能检查自己使用的因子是否具备 V2 契约。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")
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
        }
    )
    repository.upsert_strategy_instance(
        {
            "strategy_id": "quality_test",
            "name": "Quality Test",
            "template_id": "factor_topn_monthly",
            "status": "research",
            "enabled": False,
            "factors": [
                {"factor_id": "roa", "weight": 0.5},
                {"factor_id": "missing_factor", "weight": 0.5},
            ],
        }
    )

    result = repository.validate_strategy_factor_contracts("quality_test")

    assert result["status"] == "FAIL"
    assert result["missing_factors"] == ["missing_factor"]
    assert result["covered_factors"] == ["roa"]
