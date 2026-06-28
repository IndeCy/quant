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
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    QUALITY_COLUMNS,
    START_DATE,
    attach_financial_dbs,
    build_quality_selections,
    create_signal_date_table,
    load_quality_candidates,
    score_quality_frame,
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


REPORT_PATH = Path("reports/quality_cleanup_audit.md")
CLEAN_HOLDINGS_PATH = Path("reports/quality_cleanup_holdings.csv")
CURRENT_HOLDINGS_PATH = Path("reports/quality_current_holdings_for_comparison.csv")


def create_annual_financial_asof_table(con) -> None:
    """构造只使用 1231 年报的 f_ann_date as-of 快照。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE financial_quality_asof_annual AS
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
        clean_fina AS (
            SELECT
                f.ts_code AS symbol,
                f.end_date,
                p.f_ann_date,
                CAST(f.roe AS DOUBLE) AS roe,
                CAST(f.roa AS DOUBLE) AS roa,
                CAST(f.ocf_to_or AS DOUBLE) AS ocf_to_or,
                CAST(f.debt_to_assets AS DOUBLE) AS debt_to_assets,
                CAST(f.tr_yoy AS DOUBLE) AS tr_yoy
            FROM fina_db.default_table f
            JOIN publish_dates p ON f.ts_code = p.ts_code AND f.end_date = p.end_date
            WHERE p.f_ann_date IS NOT NULL
        ),
        ranked AS (
            SELECT
                d.signal_date,
                q.*,
                ROW_NUMBER() OVER(
                    PARTITION BY d.signal_date, q.symbol
                    ORDER BY q.end_date DESC, q.f_ann_date DESC
                ) AS rn
            FROM quality_signal_dates d
            JOIN clean_fina q ON q.f_ann_date <= d.signal_date
        )
        SELECT signal_date, symbol, end_date, f_ann_date, roe, roa, ocf_to_or, debt_to_assets, tr_yoy
        FROM ranked
        WHERE rn = 1
        """
    )


def create_current_financial_asof_table(con) -> None:
    """构造当前 Quality V1 的任意报告期 as-of 快照。"""
    from examples.quality_strategy_v1 import create_financial_asof_table

    create_financial_asof_table(con)


def load_annual_candidates(con) -> pd.DataFrame:
    """读取清理版候选池，包含上市和 ST/退市审计字段。"""
    return con.execute(
        """
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT
                f.trade_date AS signal_date,
                f.symbol,
                h.name AS asof_name,
                ROW_NUMBER() OVER(
                    PARTITION BY f.trade_date, f.symbol
                    ORDER BY h.start_date DESC
                ) AS rn
            FROM features f
            JOIN name_history h ON f.symbol = h.ts_code
             AND h.start_date <= f.trade_date
             AND (h.end_date IS NULL OR h.end_date >= f.trade_date)
            WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
        )
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            COALESCE(na.asof_name, sb.name) AS name,
            sb.list_status,
            sb.list_date,
            sb.delist_date,
            f.close,
            f.amount,
            f.amount_p20,
            f.volume,
            f.st_name,
            q.end_date,
            q.f_ann_date,
            q.roe,
            q.roa,
            q.ocf_to_or,
            q.debt_to_assets,
            q.tr_yoy
        FROM features f
        JOIN financial_quality_asof_annual q ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def apply_quality_cleanup_filters(frame: pd.DataFrame, quantile_filter: bool = True) -> pd.DataFrame:
    """执行上市满3年、ST/退市、1231年报和 ROE/ROA 分位清理。"""
    data = frame.copy()
    signal_dt = pd.to_datetime(data["signal_date"], format="%Y%m%d")
    list_dt = pd.to_datetime(data["list_date"], format="%Y%m%d", errors="coerce")
    delist_dt = pd.to_datetime(data["delist_date"], format="%Y%m%d", errors="coerce")
    listed_years = (signal_dt - list_dt).dt.days / 365.25
    delisted_asof = delist_dt.notna() & (delist_dt <= signal_dt)
    valid = (
        (listed_years >= 3)
        & data["st_name"].isna()
        & ~data["name"].fillna("").str.contains("ST|退", regex=True)
        & ~delisted_asof
        & data["end_date"].astype(str).str.endswith("1231")
        & data[QUALITY_COLUMNS].notna().all(axis=1)
    )
    data = data[valid].copy()
    if not quantile_filter or data.empty:
        return data

    kept = []
    for _, group in data.groupby("signal_date", sort=True):
        roe_low, roe_high = group["roe"].quantile([0.05, 0.95])
        roa_low, roa_high = group["roa"].quantile([0.05, 0.95])
        filtered = group[
            group["roe"].between(roe_low, roe_high, inclusive="both")
            & group["roa"].between(roa_low, roa_high, inclusive="both")
        ]
        kept.append(filtered)
    return pd.concat(kept, ignore_index=True) if kept else data.iloc[0:0].copy()


def build_top20_from_candidates(candidates: pd.DataFrame) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按当前 Quality 打分逻辑生成 Top20。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_frame(group)
        top = scored.head(20).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    if not holdings:
        return selections, pd.DataFrame()
    return selections, pd.concat(holdings, ignore_index=True)


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
