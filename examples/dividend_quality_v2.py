"""Dividend Quality V2 研究。

V2 使用 Tushare 标准 `dividend` 数据，本地 DuckDB 缓存后按
`ex_date <= signal_date` 构造 trailing dividend yield，避免未来分红预案穿越。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.dividend_quality_report import render_dividend_quality_report
from backtest.execution_model import ExecutionModel
from data.tushare_dividend_incremental import DividendDuckDBStore, TushareDividendProClient, TushareDividendUpdater
from examples.dividend_quality_v1 import (
    add_industry_and_size,
    add_calmar,
    apply_dividend_quality_filters,
    build_dividend_quality_selections,
    build_coverage_report,
    create_dividend_quality_asof_table,
    inspect_local_dividend_sources,
    summarize_distribution,
)
from examples.quality_cleanup_audit import (
    add_stock_basic,
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    attach_financial_dbs,
    create_signal_date_table,
)
from examples.strategy_comparison_research import (
    build_metrics_table,
    create_feature_table,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    run_monthly_backtest,
)
from backtest.research_benchmark import load_hs300_benchmark


DIVIDEND_PATH = Path("data/dividend_increment.duckdb")
REPORT_PATH = Path("reports/dividend_quality_v2.md")


def update_dividend_cache(end_date: str) -> list[str]:
    """用 Tushare 更新标准分红缓存。"""
    token = os.getenv("TUSHARE_TOKEN", "")
    if not token:
        raise RuntimeError("未检测到TUSHARE_TOKEN，无法更新标准分红数据")
    store = DividendDuckDBStore(DIVIDEND_PATH)
    result = TushareDividendUpdater(TushareDividendProClient(token), store).update_through(end_date)
    return result.updated_dates


def build_trailing_dividend_asof(
    signal_dates: list[str],
    dividends: pd.DataFrame,
    prices: pd.DataFrame,
    lookback_days: int = 365,
) -> pd.DataFrame:
    """按除息日可见性计算滚动12个月股息率。"""
    if dividends.empty or prices.empty:
        return pd.DataFrame(columns=["signal_date", "symbol", "trailing_cash_dividend", "trailing_dividend_yield"])
    implemented = dividends[
        dividends["div_proc"].astype(str).eq("实施")
        & dividends["ex_date"].notna()
        & (pd.to_numeric(dividends["cash_div_tax"], errors="coerce") > 0)
    ].copy()
    if implemented.empty:
        return pd.DataFrame(columns=["signal_date", "symbol", "trailing_cash_dividend", "trailing_dividend_yield"])
    implemented["ex_dt"] = pd.to_datetime(implemented["ex_date"], format="%Y%m%d", errors="coerce")
    implemented["cash_div_tax"] = pd.to_numeric(implemented["cash_div_tax"], errors="coerce")
    rows = []
    for signal_date, group in prices.groupby("signal_date", sort=True):
        if str(signal_date) not in set(signal_dates):
            continue
        signal_dt = pd.to_datetime(str(signal_date), format="%Y%m%d")
        start_dt = signal_dt - pd.Timedelta(days=lookback_days)
        visible = implemented[(implemented["ex_dt"] <= signal_dt) & (implemented["ex_dt"] > start_dt)]
        if visible.empty:
            continue
        dividend_sum = visible.groupby("ts_code")["cash_div_tax"].sum()
        for row in group.itertuples(index=False):
            cash = float(dividend_sum.get(row.symbol, 0.0))
            close = float(row.close)
            if cash <= 0 or close <= 0:
                continue
            rows.append(
                {
                    "signal_date": str(signal_date),
                    "symbol": row.symbol,
                    "trailing_cash_dividend": cash,
                    "trailing_dividend_yield": cash / close,
                }
            )
    return pd.DataFrame(rows)


def create_dividend_quality_v2_asof_table(con, dividends: pd.DataFrame) -> None:
    """把标准分红 trailing yield 接入候选池。"""
    signal_dates = load_signal_dates(con)
    prices = con.execute(
        """
        SELECT trade_date AS signal_date, symbol, close
        FROM features
        WHERE trade_date IN (SELECT signal_date FROM quality_signal_dates)
        """
    ).fetchdf()
    trailing = build_trailing_dividend_asof(signal_dates, dividends, prices)
    con.register("trailing_dividend_input", trailing)
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE trailing_dividend_asof AS
        SELECT * FROM trailing_dividend_input
        """
    )


def load_dividend_quality_v2_candidates(con) -> pd.DataFrame:
    """读取带真实 trailing dividend yield 的红利质量候选池。"""
    frame = con.execute(
        """
        WITH name_history AS (
            SELECT ts_code, name, start_date, end_date FROM stock_namechange
            UNION ALL
            SELECT ts_code, name, start_date, end_date FROM stock_name_manual
        ),
        name_asof AS (
            SELECT f.trade_date AS signal_date, f.symbol, h.name AS asof_name,
                   ROW_NUMBER() OVER(PARTITION BY f.trade_date, f.symbol ORDER BY h.start_date DESC) AS rn
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
            q.total_share,
            q.net_profit_parent,
            t.trailing_cash_dividend AS dividend_amount_proxy,
            t.trailing_dividend_yield AS dividend_yield_proxy,
            t.trailing_dividend_yield,
            CASE WHEN q.net_profit_parent > 0 AND q.total_share > 0
                 THEN t.trailing_cash_dividend * q.total_share / q.net_profit_parent
            END AS payout_ratio,
            1 AS dividend_consistency
        FROM features f
        JOIN dividend_quality_asof q ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        JOIN trailing_dividend_asof t ON f.trade_date = t.signal_date AND f.symbol = t.symbol
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()
    return frame


def score_dividend_quality_v2_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """V2 分数：40%真实股息率，30%ROE/ROA，30%经营现金流质量。"""
    data = frame.copy()
    data["dividend_yield_proxy"] = data["trailing_dividend_yield"]
    from examples.dividend_quality_v1 import score_dividend_quality_frame

    return score_dividend_quality_frame(data)


def build_v2_selections(candidates: pd.DataFrame) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按 V2 打分生成 Top20。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        top = score_dividend_quality_v2_frame(group).head(20).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    return (selections, pd.concat(holdings, ignore_index=True)) if holdings else (selections, pd.DataFrame())


def run_study(update_data: bool = True) -> None:
    """运行 Dividend Quality V2 研究。"""
    import duckdb

    if update_data:
        update_dividend_cache("20260624")
    audit, source_coverage = inspect_local_dividend_sources()
    audit["has_standard_dividend_table"] = DIVIDEND_PATH.exists()
    audit["standard_dividend_tables"] = ["tushare.dividend"]
    audit["proxy_fields"] = ["cash_div_tax", "ex_date", "imp_ann_date"]
    dividends = DividendDuckDBStore(DIVIDEND_PATH).load()
    with duckdb.connect(":memory:") as con:
        con.execute(f"ATTACH DATABASE '{DB_PATH}' AS main_db (READ_ONLY)")
        for table in ["daily", "daily_adj_cache", "stock_basic", "stock_st", "stock_namechange", "stock_name_manual"]:
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM main_db.{table}")
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_dividend_quality_asof_table(con)
        create_annual_financial_asof_table(con)
        create_dividend_quality_v2_asof_table(con, dividends)
        raw = load_dividend_quality_v2_candidates(con)
        filtered = apply_dividend_quality_filters(raw)
        selections, holdings = build_v2_selections(filtered)
        quality_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        quality_selections, _ = build_top20_from_candidates(quality_candidates)
        holdings = add_stock_basic(holdings, con)
        holdings = add_industry_and_size(holdings)
        coverage = build_coverage_report(raw, filtered)
        all_symbols = sorted(set(holdings["symbol"].tolist()) | {s for symbols in quality_selections.values() for s in symbols})
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        benchmark, _ = load_hs300_benchmark(con, "20150101", str(FUND_DAILY_PATH), str(FUND_BASIC_PATH))
        dividend_result = run_monthly_backtest("Dividend Quality V2", selections, bars, calendar, ExecutionModel(slippage_bps=5.0))
        quality_result = run_monthly_backtest("Quality Alpha V1", quality_selections, bars, calendar, ExecutionModel(slippage_bps=5.0))
        metrics = add_calmar(build_metrics_table({"Dividend Quality V2": dividend_result, "Quality Alpha V1": quality_result}, benchmark))
    latest_date = max(holdings["signal_date"]) if not holdings.empty else ""
    latest_holdings = holdings[holdings["signal_date"].eq(latest_date)].sort_values("rank") if latest_date else holdings
    industry_dist = summarize_distribution(holdings, "industry_level1")
    size_dist = summarize_distribution(holdings, "market_cap_bucket")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        render_dividend_quality_report(
            audit,
            source_coverage,
            coverage,
            metrics,
            industry_dist,
            size_dist,
            latest_holdings,
            strategy_label="Dividend Quality V2",
            asof_note=(
                "财务因子仅使用 `f_ann_date <= signal_date` 的 1231 年报数据；"
                "分红因子仅使用 `div_proc='实施'` 且 `ex_date <= signal_date` 的现金分红。"
            ),
            dividend_note=(
                "使用 Tushare 标准 `dividend` 表的 `cash_div_tax`，"
                "按过去365天已除息现金分红 / 信号日收盘价计算 trailing dividend yield。"
            ),
            conclusion=(
                "V2 已从财报科目弱代理升级为标准实施分红口径，当前结果可以用于判断"
                "红利收益、质量暴露与可交易性的初步关系。"
            ),
            next_step_note=(
                "本研究没有调参，也没有新增 Alpha 因子；若后续继续推进，应重点审计"
                "连续分红稳定性、行业集中和高股息陷阱，而不是直接追求更高收益。"
            ),
            risk_notes=[
                "标准分红实施数据已接入，但连续分红稳定性目前只做了占位，没有形成独立约束。",
                "支付率使用每股现金分红、总股本和归母净利润近似计算，仍需进一步核验单位和报告期匹配。",
                "行业覆盖仍依赖项目内置行业映射，最新持仓未知行业占比较高，会影响行业归因可信度。",
                "当前 V2 回测显著跑输 Quality Alpha V1，暂不应作为生产观察主策略。",
            ],
        ),
        encoding="utf-8",
    )
    print(REPORT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    run_study(update_data=True)
