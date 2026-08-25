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


def register_quality_value_lowvol_v0(repository: SystemRepository) -> None:
    """登记防御型 Quality、估值与低波五因子资产。"""
    factors = [
        (
            "earnings_yield",
            "Earnings Yield",
            "value",
            "fina_indicator+daily",
            "公告日可见年度EPS/信号日未复权收盘价。",
            ["eps", "f_ann_date", "raw_close", "adj_factor"],
        ),
        (
            "book_yield",
            "Book Yield",
            "value",
            "fina_indicator+daily",
            "公告日可见年度BPS/信号日未复权收盘价。",
            ["bps", "f_ann_date", "raw_close", "adj_factor"],
        ),
        (
            "low_volatility_60d",
            "Low Volatility 60D",
            "risk",
            "daily_adj_cache",
            "过去60个交易日日收益标准差取负。",
            ["trade_date", "close_qfq"],
        ),
    ]
    for factor_id, name, category, source, description, input_fields in factors:
        financial = factor_id != "low_volatility_60d"
        repository.upsert_factor_contract(
            factor_id=factor_id,
            name=name,
            category=category,
            direction="higher_is_better",
            source=source,
            description=description,
            version="v0",
            status="active",
            frequency="monthly",
            value_type="numeric",
            as_of_policy="financial_announcement" if financial else "trade_date",
            as_of_field="f_ann_date" if financial else "trade_date",
            effective_date_field="trade_date",
            input_datasets=["fina_indicator_duckdb", "live_market_view"] if financial else ["live_market_view"],
            input_fields=input_fields,
            output_fields=["trade_date", "symbol", "factor_value"],
            validation={
                "winsorize": [0.01, 0.99],
                "zscore": True,
                "adjust_policy": "qfq",
                "corporate_action_consistent": financial,
                "corporate_action_materiality_threshold": 0.10 if financial else None,
            },
            config={"window": 60} if not financial else {"report_period": "1231"},
        )
    repository.upsert_strategy(
        strategy_id="quality_value_lowvol_v0",
        name="Quality Value LowVol V0",
        status="retired",
        strategy_type="factor_topn_monthly",
        description="ROA、现金流、盈利收益率、账面收益率与低波等权，Top20月频并叠加固定波动率风险层。",
        config={
            "top_n": 20,
            "rebalance": "monthly",
            "risk_layer": "volatility_overlay_20d_45pct_30pct",
            "adjust_policy": "qfq",
            "definition_version": "0.1.0",
        },
    )
    repository.replace_strategy_factors(
        "quality_value_lowvol_v0",
        [
            {"factor_id": factor_id, "weight": 0.2, "transform": "winsorize_1_99_zscore"}
            for factor_id in ["roa", "ocf_to_or", "earnings_yield", "book_yield", "low_volatility_60d"]
        ],
    )


def register_quality_balanced_value_v1(repository: SystemRepository) -> None:
    """登记只进入前瞻Paper的Quality与点时估值组合。"""
    repository.upsert_strategy(
        strategy_id="quality_balanced_value_v1",
        name="Quality Balanced Value V1",
        status="shadow_live",
        strategy_type="factor_topn_monthly",
        description="Quality V1占80%，点时E/P与B/P各占10%，Top20月频并复用原风险层。",
        config={
            "top_n": 20,
            "rebalance": "monthly",
            "risk_layer": "volatility_overlay_20d_45pct_30pct",
            "adjust_policy": "qfq",
            "definition_version": "1.0.0",
            "deployment_scope": "forward_paper_only",
        },
    )
    repository.replace_strategy_factors(
        "quality_balanced_value_v1",
        [
            {"factor_id": "roe", "weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
            {"factor_id": "roa", "weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
            {"factor_id": "ocf_to_or", "weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
            {"factor_id": "earnings_yield", "weight": 0.10, "transform": "winsorize_1_99_zscore"},
            {"factor_id": "book_yield", "weight": 0.10, "transform": "winsorize_1_99_zscore"},
        ],
    )


def register_quality_defensive_assets_v2(repository: SystemRepository) -> None:
    """登记通过研究与执行门禁的核心风险预算防守组合。"""
    strategy_id = "quality_defensive_assets_core_scoped_70_15_15_v2"
    repository.upsert_strategy(
        strategy_id=strategy_id,
        name="Quality 防守资产 V2",
        status="paper",
        strategy_type="factor_topn_monthly",
        description=(
            "Quality Balanced Value核心70%，黄金ETF与5年国债ETF各15%；"
            "20日波动率风险层只调整核心暴露，进入长期Paper观察。"
        ),
        config={
            "top_n": 20,
            "rebalance": "monthly",
            "risk_layer": "volatility_overlay_20d_45pct_30pct_core_only",
            "allocation": {
                "quality_core": 0.70,
                "518880.SH": 0.15,
                "511010.SH": 0.15,
            },
            "adjust_policy": "qfq",
            "definition_version": "2.0.0",
            "deployment_scope": "forward_paper_only",
            "research_fingerprint": strategy_id,
        },
    )
    repository.replace_strategy_factors(
        strategy_id,
        [
            {"factor_id": "roe", "weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
            {"factor_id": "roa", "weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
            {"factor_id": "ocf_to_or", "weight": 0.8 / 3, "transform": "winsorize_5_95_zscore"},
            {"factor_id": "earnings_yield", "weight": 0.10, "transform": "winsorize_1_99_zscore"},
            {"factor_id": "book_yield", "weight": 0.10, "transform": "winsorize_1_99_zscore"},
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


def register_global_defensive_equal_v1(repository: SystemRepository) -> None:
    """登记已通过研究门槛的全球三资产只观察策略。"""
    repository.upsert_strategy(
        strategy_id="global_defensive_equal_v1",
        name="全球防守三资产等权 V1",
        status="research_observation",
        strategy_type="fixed_allocation_observer",
        description=(
            "博时标普500ETF、华安黄金ETF与国泰5年国债ETF固定各三分之一，"
            "月频恢复等权；仅前瞻观察，不生成Paper或实盘订单。"
        ),
        config={
            "allocation": {
                "513500.SH": 1 / 3,
                "518880.SH": 1 / 3,
                "511010.SH": 1 / 3,
            },
            "rebalance": "monthly",
            "risk_overlay": "none",
            "adjust_policy": "qfq",
            "execution_model": "M0 ExecutionModel T+1",
            "trade_policy": "observation_only",
            "research_fingerprint": "global_defensive_equal_v1",
        },
    )


def register_builtin_strategies(repository: SystemRepository) -> None:
    """登记当前系统内置策略，供策略目录和前端运行中心统一读取。"""
    repository.delete_strategy_artifacts("mainline_chain_b")
    register_innovative_drug_observer_v0(repository)
    register_global_defensive_equal_v1(repository)
    register_quality_alpha_v1(repository)
    register_quality_value_lowvol_v0(repository)
    register_quality_balanced_value_v1(repository)
    register_quality_defensive_assets_v2(repository)
    register_mainline_chain_factor_v1(repository)
