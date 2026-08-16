"""
Quality Strategy V1 Cleanup 审计。

在不新增因子、不优化参数的前提下，检查清理规则后的组合表现。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.industry import IndustryManager
from backtest.research_benchmark import load_hs300_benchmark
from data.quality_financial import materialize_quality_financial_asof
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    START_DATE,
    attach_financial_dbs,
    build_quality_selections,
    create_signal_date_table,
    load_quality_candidates,
)
from examples.strategy_comparison_research import (
    build_metrics_table,
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)
from strategies.quality_signal import build_quality_topn
from strategies.quality_universe import (
    apply_quality_universe_filters,
    load_annual_quality_candidates,
)


REPORT_PATH = Path("reports/quality_cleanup_audit.md")
CLEAN_HOLDINGS_PATH = Path("reports/quality_cleanup_holdings.csv")
CURRENT_HOLDINGS_PATH = Path("reports/quality_current_holdings_for_comparison.csv")


def create_annual_financial_asof_table(con) -> None:
    """构造只使用 1231 年报的 f_ann_date as-of 快照。"""
    materialize_quality_financial_asof(con, annual_only=True)


def create_current_financial_asof_table(con) -> None:
    """构造当前 Quality V1 的任意报告期 as-of 快照。"""
    from examples.quality_strategy_v1 import create_financial_asof_table

    create_financial_asof_table(con)


def load_annual_candidates(con) -> pd.DataFrame:
    """读取清理版候选池，包含上市和 ST/退市审计字段。"""
    return load_annual_quality_candidates(con)


def apply_quality_cleanup_filters(frame: pd.DataFrame, quantile_filter: bool = True) -> pd.DataFrame:
    """执行上市满3年、ST/退市、1231年报和 ROE/ROA 分位清理。"""
    return apply_quality_universe_filters(frame, quantile_filter=quantile_filter)


def build_top20_from_candidates(candidates: pd.DataFrame) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按当前 Quality 打分逻辑生成 Top20。"""
    return build_quality_topn(candidates, top_n=20)


def add_industry(frame: pd.DataFrame) -> pd.DataFrame:
    """补充项目内置行业树行业标签。"""
    manager = IndustryManager()
    enriched = frame.copy()
    industries = []
    for symbol in enriched["symbol"]:
        industries.append(manager.get_industry_by_stock(symbol).get("level1", "未知"))
    enriched["industry_level1"] = industries
    return enriched


def add_stock_basic(holdings: pd.DataFrame, con) -> pd.DataFrame:
    """给当前版本持仓补充名称和上市状态字段。"""
    basic = con.execute(
        """
        SELECT ts_code AS symbol, name, list_status, list_date, delist_date
        FROM stock_basic
        """
    ).fetchdf()
    drop_columns = [column for column in ["name", "list_status", "list_date", "delist_date"] if column in holdings.columns]
    enriched = holdings.drop(columns=drop_columns).merge(basic, on="symbol", how="left")
    if "rank" not in enriched.columns:
        enriched["rank"] = enriched.groupby("signal_date").cumcount() + 1
    return enriched


def industry_distribution(holdings: pd.DataFrame) -> pd.DataFrame:
    """输出行业分布。"""
    if holdings.empty:
        return pd.DataFrame(columns=["industry_level1", "持仓记录数", "占比"])
    grouped = holdings.groupby("industry_level1").size().reset_index(name="持仓记录数")
    grouped["占比"] = grouped["持仓记录数"] / len(holdings)
    return grouped.sort_values("持仓记录数", ascending=False)


def format_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化指标表。"""
    formatted = frame.copy()
    for column in ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益"]:
        formatted[column] = formatted[column].map(format_percent)
    formatted["夏普比率"] = formatted["夏普比率"].map(lambda value: f"{value:.2f}")
    return formatted


def format_percent_table(frame: pd.DataFrame, percent_columns: list[str]) -> pd.DataFrame:
    """格式化包含百分比字段的表。"""
    formatted = frame.copy()
    for column in percent_columns:
        formatted[column] = formatted[column].map(lambda value: f"{value:.2%}")
    return formatted


def render_report(metrics: pd.DataFrame, industry: pd.DataFrame, current_holdings: pd.DataFrame, clean_holdings: pd.DataFrame) -> str:
    """渲染 Cleanup 审计报告。"""
    latest_clean = clean_holdings[clean_holdings["signal_date"].eq(clean_holdings["signal_date"].max())]
    latest_current = current_holdings[current_holdings["signal_date"].eq(current_holdings["signal_date"].max())]
    latest_columns = ["signal_date", "rank", "symbol", "name", "roe", "roa", "ocf_to_or", "end_date", "f_ann_date"]
    return f"""# Quality Cleanup Audit

## 清理规则

- 上市满 3 年。
- 剔除信号日已 ST、*ST、名称含退、以及 `delist_date <= signal_date` 的已退市股票。
- 仅使用 `1231` 年报，并且 `f_ann_date <= 调仓信号日`。
- ROE/ROA 横截面 5%-95% 分位过滤。
- 因子仍为 ROE、ROA、`ocf_to_or`，不新增因子，不优化收益。

## 当前版本 vs Cleanup 版本

{markdown_table(format_metrics(metrics))}

## Cleanup 最新一期持仓名单

{markdown_table(latest_clean[latest_columns])}

## 当前版本最新一期持仓名单

{markdown_table(latest_current[latest_columns])}

## Cleanup 行业分布

{markdown_table(format_percent_table(industry, ["占比"]))}

## 数据文件

- Cleanup 完整持仓：`{CLEAN_HOLDINGS_PATH}`
- 当前版本对照持仓：`{CURRENT_HOLDINGS_PATH}`

## 备注

这里的“退市过滤”不再使用当前 `list_status=D` 提前剔除历史股票；
只有 `delist_date <= signal_date` 才视为信号日已退市。
ST/退市名称优先使用 `stock_namechange/stock_name_manual` 在信号日可见的历史简称。
"""


def main() -> None:
    """执行 Cleanup 审计并输出报告。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)

        create_current_financial_asof_table(con)
        current_candidates = load_quality_candidates(con)
        current_selections, current_holdings = build_quality_selections(current_candidates)
        current_holdings = add_industry(add_stock_basic(current_holdings, con))

        create_annual_financial_asof_table(con)
        clean_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        clean_selections, clean_holdings = build_top20_from_candidates(clean_candidates)
        clean_holdings = add_industry(clean_holdings)

        all_symbols = sorted(
            set(clean_holdings["symbol"].tolist()) | set(current_holdings["symbol"].tolist())
        )
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        execution_model = ExecutionModel(slippage_bps=5.0)
        current_result = run_monthly_backtest("Quality V1 当前版本", current_selections, bars, calendar, execution_model)
        clean_result = run_monthly_backtest("Quality Cleanup", clean_selections, bars, calendar, execution_model)
        benchmark_curve, _ = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        metrics = build_metrics_table(
            {"Quality V1 当前版本": current_result, "Quality Cleanup": clean_result},
            benchmark_curve,
        )
        industry = industry_distribution(clean_holdings)
        CLEAN_HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        clean_holdings.to_csv(CLEAN_HOLDINGS_PATH, index=False, encoding="utf-8-sig")
        current_holdings.to_csv(CURRENT_HOLDINGS_PATH, index=False, encoding="utf-8-sig")
        REPORT_PATH.write_text(render_report(metrics, industry, current_holdings, clean_holdings), encoding="utf-8")
        print(metrics.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
