"""策略模板元数据。"""

from __future__ import annotations


def list_strategy_templates() -> list[dict[str, object]]:
    """返回当前系统支持的可实例化策略模板。"""
    return [
        {
            "template_id": "factor_topn_monthly",
            "name": "多因子TopN月频策略",
            "required_sections": ["universe", "filters", "factors", "construction", "benchmark"],
            "supported_status": ["draft", "research", "paper", "shadow_live", "paused", "archived"],
        },
        {
            "template_id": "industry_chain_momentum",
            "name": "产业链动量策略",
            "required_sections": ["universe", "construction", "benchmark"],
            "supported_status": ["paper", "shadow_live", "paused", "archived"],
        },
    ]
