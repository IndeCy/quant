"""Dividend Quality V2 失败归因分析，不优化参数、不修改权重。"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from data.tushare_dividend_incremental import DividendDuckDBStore
from examples.dividend_quality_v1 import (
    add_industry_and_size,
    apply_dividend_quality_filters,
    build_coverage_report,
    create_dividend_quality_asof_table,
    summarize_distribution,
)
from examples.dividend_quality_v2 import (
    DIVIDEND_PATH,
    build_v2_selections,
    create_dividend_quality_v2_asof_table,
    load_dividend_quality_v2_candidates,
)
from examples.quality_cleanup_audit import (
    add_stock_basic,
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import DB_PATH, attach_financial_dbs, create_signal_date_table
from examples.strategy_comparison_research import (
    INITIAL_CASH,
    create_feature_table,
    get_bar,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)

REPORT_PATH = Path("reports/dividend_quality_v2_forensics.md")


def format_percent(value: float | int | None) -> str:
    return "" if value is None or pd.isna(value) else f"{float(value):.2%}"


def format_number(value: float | int | None) -> str:
    return "" if value is None or pd.isna(value) else f"{float(value):.2f}"


def create_forensic_valuation_asof_table(con) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE forensic_valuation_asof AS
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
                CAST(c.n_cashflow_act AS DOUBLE) AS operating_cashflow
            FROM balance_db.default_table b
            JOIN publish_dates p ON b.ts_code = p.ts_code AND b.end_date = p.end_date
            LEFT JOIN income_db.default_table i ON b.ts_code = i.ts_code AND b.end_date = i.end_date
            LEFT JOIN cashflow_db.default_table c ON b.ts_code = c.ts_code AND b.end_date = c.end_date
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
        SELECT *
        FROM ranked
        WHERE rn = 1
        """
    )


def enrich_forensics(con, holdings: pd.DataFrame) -> pd.DataFrame:
    exposure = con.execute(
        """
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            v.total_share,
            v.equity_parent,
            v.net_profit_parent,
            v.operating_cashflow,
            f.close * v.total_share AS market_cap_proxy,
            CASE WHEN v.equity_parent > 0 THEN f.close * v.total_share / v.equity_parent END AS pb_proxy,
            CASE WHEN v.net_profit_parent > 0 THEN f.close * v.total_share / v.net_profit_parent END AS pe_proxy
        FROM features f
        JOIN forensic_valuation_asof v ON f.trade_date = v.signal_date AND f.symbol = v.symbol
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
        """
    ).fetchdf()
    merged = holdings.merge(exposure, on=["signal_date", "symbol"], how="left", suffixes=("", "_forensic"))
    if "total_share" not in merged.columns and "total_share_forensic" in merged.columns:
        merged["total_share"] = merged["total_share_forensic"]
    return merged


def add_standard_dividend_yield(holdings: pd.DataFrame, dividend_yield: pd.DataFrame) -> pd.DataFrame:
    merged = holdings.merge(dividend_yield, on=["signal_date", "symbol"], how="left", suffixes=("", "_std"))
    if "trailing_dividend_yield" not in merged.columns and "trailing_dividend_yield_std" in merged.columns:
        merged["trailing_dividend_yield"] = merged["trailing_dividend_yield_std"]
    if "dividend_yield_proxy" not in merged.columns:
        merged["dividend_yield_proxy"] = merged["trailing_dividend_yield"]
    return merged


def add_dividend_sustainability(holdings: pd.DataFrame, dividends: pd.DataFrame) -> pd.DataFrame:
    implemented = dividends[
        dividends["div_proc"].astype(str).eq("实施")
        & dividends["ex_date"].notna()
        & (pd.to_numeric(dividends["cash_div_tax"], errors="coerce") > 0)
    ].copy()
    implemented["ex_dt"] = pd.to_datetime(implemented["ex_date"], format="%Y%m%d", errors="coerce")
    implemented["cash_div_tax"] = pd.to_numeric(implemented["cash_div_tax"], errors="coerce")
    by_symbol = {symbol: group.sort_values("ex_dt") for symbol, group in implemented.groupby("ts_code")}
    rows = []
    for row in holdings.itertuples(index=False):
        signal_dt = pd.to_datetime(str(row.signal_date), format="%Y%m%d")
        history = by_symbol.get(row.symbol, pd.DataFrame())
        visible = history[history["ex_dt"].le(signal_dt)] if not history.empty else history
        annual = visible.groupby(visible["ex_dt"].dt.year)["cash_div_tax"].sum() if not visible.empty else pd.Series(dtype=float)
        consecutive = consecutive_dividend_years(annual, signal_dt.year)
        latest_cash = float(getattr(row, "trailing_cash_dividend", 0.0) or 0.0)
        total_share = float(getattr(row, "total_share", 0.0) or getattr(row, "total_share_forensic", 0.0) or 0.0)
        dividend_cash_total = latest_cash * total_share if min(latest_cash, total_share) > 0 else 0.0
        operating_cashflow = float(getattr(row, "operating_cashflow", 0.0) or 0.0)
        coverage = dividend_cash_total / operating_cashflow if operating_cashflow > 0 else None
        last_three = annual[annual.index >= signal_dt.year - 3]
        one_off = bool(len(last_three) >= 2 and latest_cash > 0 and latest_cash >= 2 * last_three.median())
        rows.append(
            {
                "signal_date": row.signal_date,
                "symbol": row.symbol,
                "consecutive_dividend_years": consecutive,
                "dividend_to_ocf": coverage,
                "one_off_high_dividend": one_off,
            }
        )
    return holdings.merge(pd.DataFrame(rows), on=["signal_date", "symbol"], how="left")


def consecutive_dividend_years(annual_cash: pd.Series, signal_year: int) -> int:
    years = {int(year) for year, value in annual_cash.items() if float(value) > 0}
    count = 0
    for year in range(signal_year, signal_year - 20, -1):
        if year not in years:
            break
        count += 1
    return count


def describe_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows = []
    for column in columns:
        series = pd.to_numeric(frame[column], errors="coerce").dropna() if column in frame.columns else pd.Series(dtype=float)
        rows.append(
            {
                "指标": column,
                "样本数": len(series),
                "均值": series.mean() if len(series) else None,
                "P25": series.quantile(0.25) if len(series) else None,
                "中位数": series.median() if len(series) else None,
                "P75": series.quantile(0.75) if len(series) else None,
                "P95": series.quantile(0.95) if len(series) else None,
            }
        )
    return pd.DataFrame(rows)


def strategy_profile(name: str, holdings: pd.DataFrame) -> dict[str, pd.DataFrame]:
    numeric = describe_numeric(
        holdings,
        ["pb_proxy", "pe_proxy", "trailing_dividend_yield", "roe", "roa", "ocf_to_or"],
    )
    numeric.insert(0, "策略", name)
    return {
        "industry": summarize_distribution(holdings, "industry_level1").assign(策略=name),
        "size": summarize_distribution(holdings, "market_cap_bucket").assign(策略=name),
        "numeric": numeric,
    }


def drawdown_window(values: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    running_max = values.expanding().max()
    drawdown = values / running_max - 1
    trough = drawdown.idxmin()
    peak = values.loc[:trough].idxmax()
    return peak, trough, float(drawdown.loc[trough])


def reconstruct_positions(trades: list[dict[str, object]], date: pd.Timestamp) -> dict[str, int]:
    positions: dict[str, int] = {}
    for trade in trades:
        if pd.Timestamp(trade["date"]) > date:
            continue
        symbol = str(trade["symbol"])
        positions[symbol] = positions.get(symbol, 0) + int(trade["quantity"])
        if positions[symbol] == 0:
            positions.pop(symbol)
    return positions


def drawdown_contributions(
    trades: list[dict[str, object]],
    values: pd.Series,
    bars: pd.DataFrame,
    peak: pd.Timestamp,
    trough: pd.Timestamp,
    holdings: pd.DataFrame,
) -> pd.DataFrame:
    positions = reconstruct_positions(trades, peak)
    portfolio_value = float(values.loc[peak])
    names = holdings.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    industries = holdings.drop_duplicates("symbol").set_index("symbol")["industry_level1"].to_dict()
    rows = []
    for symbol, quantity in positions.items():
        start_bar = nearest_bar(bars, symbol, peak)
        end_bar = nearest_bar(bars, symbol, trough)
        if start_bar is None or end_bar is None:
            continue
        start_price = float(start_bar["close"])
        end_price = float(end_bar["close"])
        period_return = end_price / start_price - 1
        weight = quantity * start_price / portfolio_value
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "industry_level1": industries.get(symbol, "未知"),
                "weight": weight,
                "period_return": period_return,
                "loss_contribution": -weight * period_return,
            }
        )
    return pd.DataFrame(rows).sort_values("loss_contribution", ascending=False)


def nearest_bar(bars: pd.DataFrame, symbol: str, date: pd.Timestamp) -> pd.Series | None:
    bar = get_bar(bars, date, symbol)
    if bar is not None:
        return bar
    try:
        history = bars.xs(symbol, level="symbol").loc[:date]
    except KeyError:
        return None
    return history.iloc[-1] if not history.empty else None


def worst_monthly_contributors(holdings: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    rows = []
    signal_dates = sorted(holdings["signal_date"].unique().tolist())
    next_map = {date: signal_dates[idx + 1] for idx, date in enumerate(signal_dates[:-1])}
    for row in holdings.itertuples(index=False):
        end_key = next_map.get(str(row.signal_date))
        if not end_key:
            continue
        start_bar = nearest_bar(bars, row.symbol, pd.Timestamp(str(row.signal_date)))
        end_bar = nearest_bar(bars, row.symbol, pd.Timestamp(end_key))
        if start_bar is None or end_bar is None:
            continue
        ret = float(end_bar["close"]) / float(start_bar["close"]) - 1
        rows.append({"symbol": row.symbol, "name": row.name, "industry_level1": row.industry_level1, "contribution": ret / 20})
    frame = pd.DataFrame(rows)
    return (
        frame.groupby(["symbol", "name", "industry_level1"])["contribution"]
        .sum()
        .reset_index()
        .sort_values("contribution")
        .head(20)
    )


def format_profile(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ["均值", "P25", "中位数", "P75", "P95"]:
        result[column] = result.apply(
            lambda row: format_percent(row[column])
            if row["指标"] in {"trailing_dividend_yield"}
            else format_number(row[column]),
            axis=1,
        )
    return result


def format_percent_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = result[column].map(format_percent)
    return result


def render_report(
    v2_holdings: pd.DataFrame,
    quality_holdings: pd.DataFrame,
    coverage: pd.DataFrame,
    dd_info: tuple[pd.Timestamp, pd.Timestamp, float],
    dd_contrib: pd.DataFrame,
    worst: pd.DataFrame,
) -> str:
    v2_profile = strategy_profile("Dividend Quality V2", v2_holdings)
    q_profile = strategy_profile("Quality Alpha V1", quality_holdings)
    profile = pd.concat([v2_profile["numeric"], q_profile["numeric"]], ignore_index=True)
    industries = pd.concat([v2_profile["industry"], q_profile["industry"]], ignore_index=True)
    sizes = pd.concat([v2_profile["size"], q_profile["size"]], ignore_index=True)
    sustainability = describe_numeric(
        v2_holdings,
        ["payout_ratio", "consecutive_dividend_years", "dividend_to_ocf"],
    )
    one_off_ratio = float(v2_holdings["one_off_high_dividend"].fillna(False).mean())
    high_div_tokens = ["银行", "煤炭", "电力", "发电", "供气", "供热", "水务", "公用", "地产"]
    high_div_industries = dd_contrib[
        dd_contrib["industry_level1"].map(lambda item: any(token in str(item) for token in high_div_tokens))
    ]
    unknown_ratio = float(v2_holdings["industry_level1"].eq("未知").mean())
    industry_note = (
        f"行业映射未知占比已降至 {unknown_ratio:.2%}，本轮行业归因可信度较补齐前显著改善。"
        if unknown_ratio < 0.05
        else f"行业映射未知占比仍有 {unknown_ratio:.2%}，行业归因仍需谨慎。"
    )
    peak, trough, max_dd = dd_info
    top_contrib = dd_contrib.head(20).copy()
    industry_loss = (
        dd_contrib.groupby("industry_level1")
        .agg(weight=("weight", "sum"), loss_contribution=("loss_contribution", "sum"))
        .reset_index()
        .sort_values("loss_contribution", ascending=False)
    )
    style = judge_style(v2_holdings, one_off_ratio, high_div_industries, dd_contrib)
    return f"""# Dividend Quality V2 Forensics

## 1. 持仓画像

### 行业分布

{markdown_table(format_percent_columns(industries, ["占比"]).head(30))}

### 市值分布

{markdown_table(format_percent_columns(sizes, ["占比"]))}

### PB / PE / 股息率 / 质量因子分布

{markdown_table(format_profile(profile))}

### 分红覆盖度

{markdown_table(coverage.tail(12))}

## 2. 分红可持续性分析

{markdown_table(format_profile(sustainability))}

- 一次性高分红持仓记录占比：`{one_off_ratio:.2%}`。
- 口径：连续分红年限使用 `div_proc='实施'` 且 `ex_date <= signal_date` 的可见现金分红年份；分红/经营现金流覆盖使用 trailing 12个月每股现金分红乘总股本，再除以 as-of 年报经营现金流。

## 3. 回撤与亏损来源

- 最大回撤区间：`{peak.date()}` 至 `{trough.date()}`。
- 最大回撤：`{max_dd:.2%}`。

### 最大回撤区间主要持仓贡献

{markdown_table(format_percent_columns(top_contrib, ["weight", "period_return", "loss_contribution"]))}

### 回撤期行业损失贡献

{markdown_table(format_percent_columns(industry_loss, ["weight", "loss_contribution"]))}

### 全样本最差贡献前20股票

{markdown_table(format_percent_columns(worst, ["contribution"]))}

- 最大回撤起点持仓中，银行/煤炭/公用/地产等典型高股息行业合计权重：`{high_div_industries["weight"].sum():.2%}`。

## 4. 风格暴露判断

当前 V2 更像：`{style}`。

核心原因：

1. V2 的股息率约束把组合明显推向“高股息可见收益”，但连续分红稳定性没有真正进入打分，当前只是占位。
2. 支付率和分红/经营现金流覆盖显示，部分股票存在高分红但现金流覆盖压力，容易落入高股息陷阱。
3. 与 Quality Alpha V1 对比，V2 没有明显提升质量暴露，却引入了更高换手和更弱收益。
4. {industry_note}

## 5. V3 最值得优先尝试的 3 个方向

1. 先做“红利可持续性审计层”：连续分红年限、分红/经营现金流覆盖、支付率异常都作为剔除或风险标签，而不是调权重刷收益。
2. 做“高股息陷阱过滤”：识别一次性高分红、利润下滑但高支付、经营现金流无法覆盖分红的样本，先看剔除前后画像变化。
3. 做行业归因复核：确认亏损是否长期来自水泥、电力、煤炭、地产、银行等高股息行业暴露，必要时研究行业上限，但不要先调因子权重。
"""

def judge_style(
    holdings: pd.DataFrame,
    one_off_ratio: float,
    high_div_industries: pd.DataFrame,
    dd_contrib: pd.DataFrame,
) -> str:
    median_yield = pd.to_numeric(holdings["trailing_dividend_yield"], errors="coerce").median()
    median_roe = pd.to_numeric(holdings["roe"], errors="coerce").median()
    median_ocf_cover = pd.to_numeric(holdings["dividend_to_ocf"], errors="coerce").median()
    weak_quality = median_roe < 15 or one_off_ratio > 0.25 or median_ocf_cover > 0.8
    high_div_weight = high_div_industries["weight"].sum() if not dd_contrib.empty else 0.0
    if weak_quality:
        return "C. 低质量高股息股"
    if high_div_weight > 0.35:
        return "B. 周期高股息股"
    if median_yield > 0.03:
        return "A. 高股息价值股"
    return "D. 真正的红利质量股"


def main() -> None:
    import duckdb

    dividends = DividendDuckDBStore(DIVIDEND_PATH).load()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_dividend_quality_asof_table(con)
        create_annual_financial_asof_table(con)
        create_forensic_valuation_asof_table(con)
        create_dividend_quality_v2_asof_table(con, dividends)
        raw_v2 = load_dividend_quality_v2_candidates(con)
        filtered_v2 = apply_dividend_quality_filters(raw_v2)
        v2_selections, v2_holdings = build_v2_selections(filtered_v2)
        quality_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        quality_selections, quality_holdings = build_top20_from_candidates(quality_candidates)

        dividend_yield = con.execute("SELECT * FROM trailing_dividend_asof").fetchdf()
        v2_holdings = enrich_forensics(con, add_stock_basic(v2_holdings, con))
        quality_holdings = enrich_forensics(con, add_stock_basic(quality_holdings, con))
        v2_holdings = add_industry_and_size(v2_holdings)
        quality_holdings = add_industry_and_size(quality_holdings)
        v2_holdings = add_standard_dividend_yield(v2_holdings, dividend_yield)
        quality_holdings = add_standard_dividend_yield(quality_holdings, dividend_yield)
        v2_holdings = add_dividend_sustainability(v2_holdings, dividends)

        all_symbols = sorted(set(v2_holdings["symbol"]) | set(quality_holdings["symbol"]))
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        result = run_monthly_backtest(
            "Dividend Quality V2",
            v2_selections,
            bars,
            calendar,
            ExecutionModel(slippage_bps=5.0),
        )
        dd_info = drawdown_window(result.daily_values)
        dd_contrib = drawdown_contributions(result.trades, result.daily_values, bars, dd_info[0], dd_info[1], v2_holdings)
        worst = worst_monthly_contributors(v2_holdings, bars)
        coverage = build_coverage_report(raw_v2, filtered_v2)
        REPORT_PATH.write_text(
            render_report(v2_holdings, quality_holdings, coverage, dd_info, dd_contrib, worst),
            encoding="utf-8",
        )
        print(REPORT_PATH.read_text(encoding="utf-8"))
    finally:
        con.close()


if __name__ == "__main__":
    main()
