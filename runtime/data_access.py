"""从运行路径构造统一量化数据快照。"""

from __future__ import annotations

from data.dataset_contract import DatasetBinding, DatasetContract
from data.financial_duckdb_source import DuckDBFinancialDataSource
from data.market_snapshot import create_fund_market_snapshot, create_market_snapshot
from data.quant_data_portal import QuantDataSnapshot
from runtime.paths import RuntimePaths, get_runtime_paths


def create_quant_data_snapshot(
    as_of_date: str,
    *,
    paths: RuntimePaths | None = None,
    lookback_start: str = "20140701",
) -> QuantDataSnapshot:
    """创建策略可注入的统一只读数据快照。"""
    runtime_paths = paths or get_runtime_paths()
    stock_market = create_market_snapshot(
        runtime_paths.base_market_path,
        runtime_paths.live_market_increment_path,
        as_of_date,
        lookback_start=lookback_start,
        adjust_policy="qfq",
    )
    fund_market = create_fund_market_snapshot(
        runtime_paths.fund_daily_history_path,
        runtime_paths.benchmark_increment_path,
        as_of_date,
        lookback_start=lookback_start,
        adjust_policy="qfq",
    )

    def load_financial_portal():
        return DuckDBFinancialDataSource(
            {
                "income": runtime_paths.income_statement_path,
                "balancesheet": runtime_paths.balance_sheet_path,
                "cashflow": runtime_paths.cashflow_statement_path,
                "fina_indicator": runtime_paths.fina_indicator_path,
                "forecast": runtime_paths.forecast_path,
                "express": runtime_paths.earnings_express_path,
            }
        ).get_financial_portal()

    return QuantDataSnapshot(
        as_of_date=as_of_date,
        stock_market=stock_market,
        fund_market=fund_market,
        financial_portal=load_financial_portal,
        datasets=_default_bindings(runtime_paths),
    )


def _default_bindings(paths: RuntimePaths) -> list[DatasetBinding]:
    """登记现有数据资产的稳定逻辑名称，不复制任何数据。"""
    definitions = [
        (_contract("market.daily_basic", "daily_basic", ("trade_date", "ts_code"), "trade_date", "ts_code", "day", "A股估值、市值和换手率"), paths.beta_increment_path),
        (_contract("market.index_dailybasic", "index_dailybasic", ("trade_date", "ts_code"), "trade_date", "ts_code", "day", "指数估值和成交指标"), paths.beta_increment_path),
        (_contract("fund.share", "fund_share", ("trade_date", "ts_code"), "trade_date", "ts_code", "day", "ETF/基金份额"), paths.beta_increment_path),
        (_contract("flow.hsgt", "moneyflow_hsgt", ("trade_date",), "trade_date", None, "day", "沪深港通资金汇总"), paths.beta_increment_path),
        (_contract("margin.market", "margin", ("trade_date", "exchange_id"), "trade_date", None, "day", "融资融券市场汇总"), paths.beta_increment_path),
        (_contract("margin.detail", "margin_detail", ("trade_date", "ts_code"), "trade_date", "ts_code", "day", "融资融券个股明细"), paths.margin_trade_path),
        (_contract("market.limit_list", "limit_list_daily", ("trade_date", "ts_code", "limit_type"), "trade_date", "ts_code", "day", "涨跌停与炸板记录"), paths.limit_list_increment_path),
        (_contract("flow.order", "order_flow_daily", ("trade_date", "ts_code"), "trade_date", "ts_code", "day", "个股大小单资金流"), paths.order_flow_path),
        (_contract("flow.top_inst", "top_inst_events", ("event_key",), "trade_date", "ts_code", "event", "龙虎榜机构交易"), paths.top_inst_path),
        (_contract("event.block_trade", "block_trade_events", ("event_key", "duplicate_ordinal"), "trade_date", "ts_code", "event", "大宗交易"), paths.block_trade_path),
        (_contract("event.shareholder_count", "shareholder_count_events", ("ts_code", "ann_date", "end_date"), "ann_date", "ts_code", "event", "股东户数披露"), paths.shareholder_count_path),
        (_contract("event.holder_trade", "holder_trade_events", ("event_key",), "ann_date", "ts_code", "event", "重要股东增减持"), paths.holder_trade_path),
        (_contract("event.dividend", "dividend", ("ts_code", "end_date", "ann_date", "div_proc"), "ann_date", "ts_code", "event", "分红送股"), paths.dividend_path),
        (_contract("fund.ownership", "fund_product_top10", ("end_date", "product_key", "symbol", "position_rank"), "ann_date", "symbol", "quarter", "公募基金披露持仓"), paths.fund_ownership_path),
        (_contract("reference.stock_industry", "stock_industry", ("ts_code",), None, "ts_code", "snapshot", "股票行业基础映射"), paths.industry_increment_path),
        (_contract("reference.concept_member", "concept_member", ("theme_id", "provider", "index_code", "con_code"), None, "con_code", "snapshot", "概念板块成分"), paths.opportunity_concept_increment_path),
    ]
    return [DatasetBinding(contract, path) for contract, path in definitions]


def _contract(
    dataset_id: str,
    table_name: str,
    primary_key: tuple[str, ...],
    date_field: str | None,
    symbol_field: str | None,
    frequency: str,
    description: str,
) -> DatasetContract:
    return DatasetContract(
        dataset_id=dataset_id,
        table_name=table_name,
        primary_key=primary_key,
        date_field=date_field,
        symbol_field=symbol_field,
        provider="tushare",
        frequency=frequency,
        description=description,
    )
