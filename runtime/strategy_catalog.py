"""内置策略与因子元数据登记。"""

from __future__ import annotations

from runtime.repository import SystemRepository


def register_quality_alpha_v1(repository: SystemRepository) -> None:
    """登记当前生产候选 Quality Alpha V1，不改变策略计算逻辑。"""
    factors = [
        ("roe", "ROE", "quality", "higher_is_better", "fina_indicator", "净资产收益率"),
        ("roa", "ROA", "quality", "higher_is_better", "fina_indicator", "总资产收益率"),
        ("ocf_to_or", "OCF_TO_OR", "quality", "higher_is_better", "fina_indicator", "经营现金流/营业收入"),
    ]
    for factor_id, name, category, direction, source, description in factors:
        repository.upsert_factor(
            factor_id=factor_id,
            name=name,
            category=category,
            direction=direction,
            source=source,
            description=description,
            config={"as_of_field": "f_ann_date", "report_period": "1231"},
        )
    repository.upsert_strategy(
        strategy_id="quality_overlay",
        name="Quality Alpha V1",
        status="active",
        strategy_type="factor_topn_monthly",
        description="ROE、ROA、OCF_TO_OR 等权打分，Top20 月频调仓，叠加20日波动率风险层。",
        config={
            "top_n": 20,
            "rebalance": "monthly",
            "risk_layer": "volatility_overlay_20d_45pct_30pct",
            "adjust_policy": "qfq",
        },
    )
    repository.replace_strategy_factors(
        "quality_overlay",
        [
            {"factor_id": "roe", "weight": 1 / 3, "transform": "winsorize_zscore"},
            {"factor_id": "roa", "weight": 1 / 3, "transform": "winsorize_zscore"},
            {"factor_id": "ocf_to_or", "weight": 1 / 3, "transform": "winsorize_zscore"},
        ],
    )
