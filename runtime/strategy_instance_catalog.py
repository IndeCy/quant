"""内置策略实例登记。"""

from __future__ import annotations

from runtime.repository import SystemRepository


def register_builtin_strategy_instances(repository: SystemRepository) -> None:
    """把当前固定策略兼容登记为可运行策略实例。"""
    repository.delete_strategy_artifacts("mainline_chain_b")
    repository.upsert_strategy_instance(
        {
            "strategy_id": "quality_overlay",
            "name": "Quality Alpha V1",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": ["listed_3y", "exclude_st", "annual_report_1231"],
            "factors": [
                {"factor_id": "roe", "weight": 1 / 3, "transform": "winsorize_zscore"},
                {"factor_id": "roa", "weight": 1 / 3, "transform": "winsorize_zscore"},
                {"factor_id": "ocf_to_or", "weight": 1 / 3, "transform": "winsorize_zscore"},
            ],
            "construction": {"top_n": 20, "weighting": "equal_weight", "rebalance": "monthly"},
            "risk_overlay": "vol_20_45_to_30",
            "benchmark": "510300",
            "config": {"adapter": "quality_overlay_compat"},
        }
    )
    repository.upsert_strategy_instance(
        {
            "strategy_id": "mainline_chain_factor_v1",
            "name": "主线链动因子 V1",
            "template_id": "factor_chain_rotation",
            "status": "shadow_live",
            "enabled": True,
            "universe": "industry_chain_pool",
            "filters": ["market_gate", "local_standard_cache", "qfq"],
            "factors": [
                {"factor_id": "mainline_chain_strength_60d", "weight": 0.4, "transform": "momentum_return"},
                {"factor_id": "mainline_stock_momentum_120d", "weight": 0.25, "transform": "momentum_return"},
                {"factor_id": "mainline_stock_momentum_60d", "weight": 0.25, "transform": "momentum_return"},
                {"factor_id": "mainline_chain_gate", "weight": 0.1, "transform": "gate_filter"},
            ],
            "construction": {
                "mode": "multi_chain",
                "top_n": 5,
                "weighting": "equal_weight",
                "rebalance_frequency": 5,
                "chain_momentum_window": 60,
            },
            "risk_overlay": "market_gate",
            "benchmark": "000001.SH",
            "config": {
                "data_cache": "data/market_cache.sqlite3",
                "provider": "tushare",
                "frequency": "1d",
                "adjust_policy": "qfq",
                "initial_capital": 1_000_000.0,
                "execution_slippage_bps": 10.0,
            },
        }
    )
