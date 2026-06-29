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


def register_mainline_chain_b(repository: SystemRepository) -> None:
    """登记主线链动 B 策略元数据，不改变既有观察和交易逻辑。"""
    repository.upsert_strategy(
        strategy_id="mainline_chain_b",
        name="主线链动策略",
        status="shadow_live",
        strategy_type="industry_chain_momentum",
        description="产业链强度轮动，选择当前最强产业链并在链内按60/120日动量等权持有Top5。",
        config={
            "entrypoint": "examples/post_close_mainline_chain_observer.py",
            "observer": "backtest.mainline_observer.observe_account",
            "execution": "backtest.mainline_rebalance_executor.execute_due_rebalance",
            "strategy_class": "backtest.chain_selection.ChainStockSelectionStrategy",
            "mode": "multi_chain",
            "top_n": 5,
            "rebalance_frequency": 5,
            "momentum_windows": [60, 120],
            "chain_momentum_window": 60,
            "chain_gate_symbol": "市场基线",
            "benchmark": "上证指数",
            "data_cache": "data/market_cache.sqlite3",
            "paper_account_id": 1,
            "automation_name": "主线链动策略盘后观察",
            "adjust_policy": "qfq_for_signal_none_for_valuation",
        },
    )


def register_builtin_strategies(repository: SystemRepository) -> None:
    """登记当前系统内置策略，供策略目录和前端运行中心统一读取。"""
    register_quality_alpha_v1(repository)
    register_mainline_chain_b(repository)
