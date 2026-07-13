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
        repository.upsert_factor_contract(
            factor_id=factor_id,
            name=name,
            category=category,
            direction=direction,
            source=source,
            description=description,
            version="v1",
            status="active",
            frequency="annual",
            value_type="numeric",
            as_of_policy="financial_announcement",
            as_of_field="f_ann_date",
            effective_date_field="trade_date",
            input_datasets=["fina_indicator_duckdb"],
            input_fields=["ts_code", "end_date", "f_ann_date", factor_id],
            output_fields=["trade_date", "symbol", "factor_value"],
            validation={"winsorize": True, "zscore": True, "report_period": "1231"},
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


def _register_mainline_chain_factors(repository: SystemRepository) -> None:
    """登记主线链动可组合因子，供原生策略和历史兼容策略共用。"""
    signal_components = [
        (
            "mainline_chain_gate",
            "市场基线过滤",
            "risk_gate",
            "higher_is_better",
            "chain_selection",
            "用市场基线判断主线链动策略是否允许进入风险资产。",
            {"gate_symbol": "市场基线"},
        ),
        (
            "mainline_chain_strength_60d",
            "产业链60日强度",
            "signal_component",
            "higher_is_better",
            "chain_selection",
            "按60日产业链动量选择当前主线方向。",
            {"window": 60},
        ),
        (
            "mainline_stock_momentum_120d",
            "个股120日动量",
            "signal_component",
            "higher_is_better",
            "chain_selection",
            "在入选产业链内部评估个股中期动量。",
            {"window": 120},
        ),
        (
            "mainline_stock_momentum_60d",
            "个股60日动量",
            "signal_component",
            "higher_is_better",
            "chain_selection",
            "在入选产业链内部评估个股短中期动量。",
            {"window": 60},
        ),
    ]
    for component in signal_components:
        factor_id, name, category, direction, source, description, config = component
        repository.upsert_factor_contract(
            factor_id=factor_id,
            name=name,
            category=category,
            direction=direction,
            source=source,
            description=description,
            version="v1",
            status="active",
            frequency="daily",
            value_type="numeric",
            as_of_policy="trade_date",
            as_of_field="trade_date",
            effective_date_field="trade_date",
            input_datasets=["market_cache_sqlite3", "live_market_increment_duckdb"],
            input_fields=["trade_date", "symbol", "close"],
            output_fields=["trade_date", "symbol", "factor_value"],
            validation={"adjust_policy": "qfq"},
            config=config,
        )


def register_mainline_chain_factor_v1(repository: SystemRepository) -> None:
    """登记主线链动原生因子组合策略。"""
    _register_mainline_chain_factors(repository)
    repository.upsert_strategy(
        strategy_id="mainline_chain_factor_v1",
        name="主线链动因子 V1",
        status="shadow_live",
        strategy_type="factor_chain_rotation",
        description="用产业链强度、市场基线过滤、链内60/120日动量组合构建主线链动观察策略。",
        config={
            "mode": "multi_chain",
            "top_n": 5,
            "rebalance_frequency": 5,
            "chain_momentum_window": 60,
            "stock_momentum_windows": [60, 120],
            "benchmark": "000001.SH",
            "data_cache": "data/market_cache.sqlite3",
            "provider": "tushare",
            "frequency": "1d",
            "adjust_policy": "qfq",
            "execution_model": "M0 ExecutionModel T+1",
        },
    )
    repository.replace_strategy_factors(
        "mainline_chain_factor_v1",
        [
            {"factor_id": "mainline_chain_gate", "weight": 0.10, "transform": "gate_filter"},
            {"factor_id": "mainline_chain_strength_60d", "weight": 0.40, "transform": "momentum_return"},
            {"factor_id": "mainline_stock_momentum_120d", "weight": 0.25, "transform": "momentum_return"},
            {"factor_id": "mainline_stock_momentum_60d", "weight": 0.25, "transform": "momentum_return"},
        ],
    )


def register_innovative_drug_observer_v0(repository: SystemRepository) -> None:
    """登记创新药出海观察策略，不生成交易调仓。"""
    repository.upsert_strategy(
        strategy_id="innovative_drug_globalization_observer_v0",
        name="创新药出海观察策略 V0",
        status="research_observation",
        strategy_type="opportunity_observer",
        description="基于创新药出海投研观察池生成Top5等权观察组合，仅用于研究观察。",
        config={
            "theme_id": "innovative_drug_globalization",
            "top_n": 5,
            "weighting": "equal_weight",
            "exclude_mature": True,
            "adjust_policy": "qfq",
            "trade_policy": "observation_only",
        },
    )


def register_builtin_strategies(repository: SystemRepository) -> None:
    """登记当前系统内置策略，供策略目录和前端运行中心统一读取。"""
    repository.delete_strategy_artifacts("mainline_chain_b")
    register_innovative_drug_observer_v0(repository)
    register_quality_alpha_v1(repository)
    register_mainline_chain_factor_v1(repository)
