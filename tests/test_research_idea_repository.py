"""研究想法资料库测试。"""

from pathlib import Path

from runtime.repository import SystemRepository


def test_factor_idea_can_be_saved_and_listed(tmp_path: Path) -> None:
    """外部因子想法应能以自然语言草案形式沉淀到本地状态库。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    saved = repository.upsert_factor_idea(
        {
            "idea_id": "profit_stability",
            "title": "盈利稳定性",
            "raw_description": "过去三年ROE波动率越低越好",
            "source": "external_note",
            "hypothesis": "盈利稳定公司更可能获得稳定估值溢价",
            "required_data": ["roe", "f_ann_date"],
            "as_of_requirement": "必须使用财报披露日",
            "direction": "lower_is_better",
            "status": "draft",
        }
    )

    ideas = repository.list_factor_ideas()

    assert saved["idea_id"] == "profit_stability"
    assert saved["required_data"] == ["roe", "f_ann_date"]
    assert ideas[0]["title"] == "盈利稳定性"
    assert ideas[0]["status"] == "draft"


def test_strategy_idea_can_be_saved_and_listed(tmp_path: Path) -> None:
    """外部策略描述应能沉淀为待结构化策略想法。"""
    repository = SystemRepository(tmp_path / "state" / "quant_system.sqlite")

    saved = repository.upsert_strategy_idea(
        {
            "idea_id": "quality_low_vol_top30",
            "title": "高质量低波Top30",
            "raw_description": "高ROA、高经营现金流、低波动，月频调仓，Top30",
            "source": "external_strategy",
            "hypothesis": "质量和低波风险溢价共同发挥作用",
            "candidate_template": "factor_topn_monthly",
            "required_factors": ["roa", "ocf_to_or", "low_volatility"],
            "status": "structured",
        }
    )

    ideas = repository.list_strategy_ideas()

    assert saved["idea_id"] == "quality_low_vol_top30"
    assert saved["required_factors"] == ["roa", "ocf_to_or", "low_volatility"]
    assert ideas[0]["candidate_template"] == "factor_topn_monthly"
