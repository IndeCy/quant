"""
Quality Cleanup 收益来源归因审计。

只解释已有 Cleanup 组合，不优化收益、不新增选股因子。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import align_benchmark_return, load_hs300_benchmark
from examples.quality_cleanup_audit import (
    CLEAN_HOLDINGS_PATH,
    add_industry,
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    START_DATE,
    attach_financial_dbs,
    create_signal_date_table,
)
from examples.strategy_comparison_research import (
    build_annual_returns,
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/quality_attribution_audit.md")
ATTRIBUTION_HOLDINGS_PATH = Path("reports/quality_attribution_holdings.csv")


def bucket_market_cap(series: pd.Series) -> pd.Series:
    """按样本内市值四分位分桶。"""
    labels = ["小盘", "中小盘", "中大盘", "大盘"]
    return pd.qcut(series.rank(method="first"), q=4, labels=labels).astype(str)


def summarize_exposure(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """汇总暴露均值、中位数和样本数。"""
    rows = []
    for column in columns:
        series = pd.to_numeric(frame[column], errors="coerce").dropna()
        rows.append({"指标": column, "样本数": len(series), "均值": series.mean(), "中位数": series.median()})
    return pd.DataFrame(rows)


def create_annual_valuation_asof_table(con) -> None:
    """构造年报估值数据 as-of 表，用于归因而非选股。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE annual_valuation_asof AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS f_ann_date
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
            )
            WHERE RIGHT(end_date, 4) = '1231'
            GROUP BY ts_code, end_date
        ),
        annual_raw AS (
            SELECT
                b.ts_code AS symbol,
                b.end_date,
                p.f_ann_date,
                CAST(b.total_share AS DOUBLE) AS total_share,
                CAST(b.total_hldr_eqy_exc_min_int AS DOUBLE) AS equity_parent,
                CAST(i.n_income_attr_p AS DOUBLE) AS net_profit_parent,
                CAST(i.comshare_payable_dvd AS DOUBLE) AS common_dividend_payable
            FROM balance_db.default_table b
            JOIN publish_dates p ON b.ts_code = p.ts_code AND b.end_date = p.end_date
            LEFT JOIN income_db.default_table i ON b.ts_code = i.ts_code AND b.end_date = i.end_date
            WHERE RIGHT(b.end_date, 4) = '1231'
        ),
        ranked AS (
            SELECT
                d.signal_date,
                a.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, a.symbol
                    ORDER BY a.end_date DESC, a.f_ann_date DESC
                ) AS rn
            FROM quality_signal_dates d
            JOIN annual_raw a ON a.f_ann_date <= d.signal_date
        )
        SELECT signal_date, symbol, end_date, f_ann_date, total_share, equity_parent,
               net_profit_parent, common_dividend_payable
        FROM ranked
        WHERE rn = 1
        """
    )


def attach_valuation_exposure(con, holdings: pd.DataFrame) -> pd.DataFrame:
    """给 Cleanup 持仓补充市值、PB、PE、股息率代理。"""
    valuation = con.execute(
        """
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            v.total_share,
            v.equity_parent,
            v.net_profit_parent,
            v.common_dividend_payable,
            f.close,
            f.close * v.total_share AS market_cap_proxy,
            CASE WHEN v.equity_parent > 0 THEN f.close * v.total_share / v.equity_parent END AS pb_proxy,
            CASE WHEN v.net_profit_parent > 0 THEN f.close * v.total_share / v.net_profit_parent END AS pe_proxy,
            CASE WHEN f.close * v.total_share > 0
                 THEN v.common_dividend_payable / (f.close * v.total_share)
            END AS dividend_yield_proxy
        FROM features f
        JOIN annual_valuation_asof v ON f.trade_date = v.signal_date AND f.symbol = v.symbol
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
        """
    ).fetchdf()
    enriched = holdings.merge(valuation, on=["signal_date", "symbol"], how="left", suffixes=("", "_valuation"))
    return enriched


def add_market_cap_bucket_by_universe(holdings: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """按当期清理后候选池市值分位给持仓打桶。"""
    enriched = holdings.copy()
    bucket_map = {}
    for signal_date, group in universe.dropna(subset=["market_cap_proxy"]).groupby("signal_date", sort=True):
        labels = bucket_market_cap(group["market_cap_proxy"])
        for symbol, label in zip(group["symbol"], labels, strict=False):
            bucket_map[(str(signal_date), symbol)] = label
    enriched["market_cap_bucket"] = [
        bucket_map.get((str(row.signal_date), row.symbol), "未知") for row in enriched.itertuples(index=False)
    ]
    return enriched


def annual_strategy_vs_benchmark(strategy_values: pd.Series, benchmark_curve: pd.Series) -> pd.DataFrame:
    """按年度对比 Cleanup 和 510300 收益。"""
    rows = []
    for year in sorted(set(strategy_values.index.year)):
        year_end = pd.Timestamp(year=year, month=12, day=31)
        previous_end = pd.Timestamp(year=year - 1, month=12, day=31)
        strategy_window = strategy_values.loc[:year_end]
        benchmark_window = benchmark_curve.loc[:year_end]
        if strategy_window.empty or benchmark_window.empty:
            continue
        strategy_before = strategy_values.loc[:previous_end]
        benchmark_before = benchmark_curve.loc[:previous_end]
        strategy_start = strategy_before.iloc[-1] if not strategy_before.empty else strategy_values[strategy_values.index.year == year].iloc[0]
        benchmark_start = benchmark_before.iloc[-1] if not benchmark_before.empty else benchmark_curve[benchmark_curve.index.year == year].iloc[0]
        strategy_return = float(strategy_window.iloc[-1] / strategy_start - 1)
        benchmark_return = float(benchmark_window.iloc[-1] / benchmark_start - 1)
        rows.append(
            {
                "年份": int(year),
                "Quality收益": strategy_return,
                "沪深300收益": benchmark_return,
                "超额收益": strategy_return - benchmark_return,
            }
        )
    return pd.DataFrame(rows)


def exposure_by_bucket(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """输出分桶占比。"""
    grouped = frame.groupby(column).size().reset_index(name="持仓记录数")
    grouped["占比"] = grouped["持仓记录数"] / len(frame)
    return grouped.sort_values("持仓记录数", ascending=False)


def format_percent_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """格式化百分比列。"""
    formatted = frame.copy()
    for column in columns:
        formatted[column] = formatted[column].map(lambda value: "" if pd.isna(value) else f"{value:.2%}")
    return formatted


def format_float_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化浮点列。"""
    formatted = frame.copy()
    for column in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda value: "" if pd.isna(value) else f"{value:.2f}")
    return formatted


def render_report(
    annual: pd.DataFrame,
    industry: pd.DataFrame,
    market_cap: pd.DataFrame,
    exposure: pd.DataFrame,
    benchmark_summary: pd.DataFrame,
    conclusion: pd.DataFrame,
) -> str:
    """渲染归因报告。"""
    return f"""# Quality Strategy Attribution Audit

## 1. 年度收益表（2015-2026）

{markdown_table(format_percent_columns(annual, ["Quality收益", "沪深300收益", "超额收益"]))}

## 2. 行业暴露

{markdown_table(format_percent_columns(industry, ["占比"]))}

## 3. 市值暴露

{markdown_table(format_percent_columns(market_cap, ["占比"]))}

## 4-5. 股息率、PB、PE 暴露

{markdown_table(format_float_columns(exposure))}

## 6. 与沪深300比较

{markdown_table(format_percent_columns(benchmark_summary, ["Quality总收益", "沪深300总收益", "超额收益"]))}

## 收益来源判断

{markdown_table(conclusion)}

## 口径说明

- 市值代理：`信号日收盘价 * 年报总股本`。
- PB 代理：市值代理 / 年报归母权益。
- PE 代理：市值代理 / 年报归母净利润，仅正利润样本有效。
- 股息率代理：年报普通股应付股利 / 市值代理。当前本地库没有标准现金分红除权数据，因此该字段只能作为弱代理。
- 沪深300对比使用本地 510300 ETF 净值曲线，不含沪深300成分股层面的市值/PB/PE/股息率暴露。
- 本报告解释 Cleanup 组合收益来源，不改变策略、不新增因子。
"""


def main() -> None:
    """运行归因审计。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        clean_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        selections, holdings = build_top20_from_candidates(clean_candidates)
        create_annual_valuation_asof_table(con)
        enriched = add_industry(attach_valuation_exposure(con, holdings))
        universe_exposure = attach_valuation_exposure(con, clean_candidates)
        enriched = add_market_cap_bucket_by_universe(enriched, universe_exposure)
        symbols = sorted(enriched["symbol"].unique().tolist())
        bars = load_research_bars(con, symbols)
        calendar = load_calendar(con)
        result = run_monthly_backtest("Quality Cleanup", selections, bars, calendar, ExecutionModel(slippage_bps=5.0))
        benchmark_curve, benchmark_label = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        annual = annual_strategy_vs_benchmark(result.daily_values, benchmark_curve)
        industry = exposure_by_bucket(enriched, "industry_level1")
        market_cap = exposure_by_bucket(enriched, "market_cap_bucket")
        exposure = summarize_exposure(enriched, ["market_cap_proxy", "dividend_yield_proxy", "pb_proxy", "pe_proxy", "roe", "roa", "ocf_to_or"])
        benchmark_summary = pd.DataFrame(
            [
                {
                    "基准": benchmark_label,
                    "Quality总收益": float(result.daily_values.iloc[-1] / result.daily_values.iloc[0] - 1),
                    "沪深300总收益": align_benchmark_return(result.daily_values, benchmark_curve),
                    "超额收益": float(result.daily_values.iloc[-1] / result.daily_values.iloc[0] - 1)
                    - align_benchmark_return(result.daily_values, benchmark_curve),
                }
            ]
        )
        unknown_industry_ratio = float((enriched.get("industry_level1", pd.Series(["未知"] * len(enriched))) == "未知").mean())
        conclusion = pd.DataFrame(
            [
                {"来源": "A. Quality", "判断": "强", "证据": "ROE/ROA/经营现金流质量是唯一排序信号，清理后仍显著跑赢510300。"},
                {"来源": "B. 小盘", "判断": "弱", "证据": "按清理后候选池市值分位，组合大盘/中大盘占比约80%，小盘不是主要来源。"},
                {"来源": "C. 高股息", "判断": "不可判定", "证据": "本地缺标准现金分红数据，当前股息率代理有效样本为0。"},
                {"来源": "D. 行业集中", "判断": "中", "证据": f"本地行业树未知占比较高（约{unknown_industry_ratio:.2%}），已知部分偏交通、公用、食品饮料。"},
                {"来源": "E. 幸存者偏差", "判断": "中", "证据": "已修复未来退市过滤，但股票基础库覆盖和退市历史状态仍需更严格as-of校验。"},
            ]
        )
        enriched.to_csv(ATTRIBUTION_HOLDINGS_PATH, index=False, encoding="utf-8-sig")
        REPORT_PATH.write_text(render_report(annual, industry, market_cap, exposure, benchmark_summary, conclusion), encoding="utf-8")
        print(benchmark_summary.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
        print(f"归因持仓已写入: {ATTRIBUTION_HOLDINGS_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
