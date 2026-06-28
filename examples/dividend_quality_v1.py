"""Dividend Quality V1 研究。

在 Quality Alpha V1 之外，研究一条红利质量策略线。当前本地没有标准
现金分红除权表，因此 V1 使用年报 `comshare_payable_dvd` 构造 as-of
股息率代理，报告中会明确标注数据限制。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.dividend_quality_report import render_dividend_quality_report
from backtest.industry import IndustryManager
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_cleanup_audit import (
    add_stock_basic,
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_strategy_v1 import (
    BALANCE_PATH,
    CASHFLOW_PATH,
    DB_PATH,
    FINA_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    INCOME_PATH,
    attach_financial_dbs,
    create_signal_date_table,
    score_quality_frame,
)
from examples.strategy_comparison_research import (
    build_metrics_table,
    create_feature_table,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/dividend_quality_v1.md")
DIVIDEND_COLUMNS = ["dividend_yield_proxy", "roe", "roa", "ocf_to_or"]


def audit_dividend_data_sources(table_columns: dict[str, list[str]]) -> dict[str, object]:
    """审计本地是否存在标准分红表和可用代理字段。"""
    dividend_table_names = [
        name
        for name in table_columns
        if any(keyword in name.lower() for keyword in ["dividend", "bonus", "dvd"])
    ]
    proxy_fields = []
    for columns in table_columns.values():
        proxy_fields.extend(column for column in columns if column in {"comshare_payable_dvd", "div_payt"})
    return {
        "has_standard_dividend_table": bool(dividend_table_names),
        "standard_dividend_tables": dividend_table_names,
        "has_income_dividend_proxy": bool({"comshare_payable_dvd", "div_payt"} & set(proxy_fields)),
        "proxy_fields": sorted(set(proxy_fields)),
    }


def inspect_local_dividend_sources() -> tuple[dict[str, object], pd.DataFrame]:
    """扫描本地 DuckDB，输出分红相关数据覆盖度。"""
    import duckdb

    db_paths = {
        "daily": DB_PATH,
        "income": INCOME_PATH,
        "balancesheet": BALANCE_PATH,
        "cashflow": CASHFLOW_PATH,
        "fina_indicator": FINA_PATH,
    }
    table_columns: dict[str, list[str]] = {}
    rows = []
    for label, path in db_paths.items():
        if not path.exists():
            rows.append({"数据源": label, "表": "-", "行数": 0, "分红相关字段": "文件缺失"})
            continue
        with duckdb.connect(str(path), read_only=True) as con:
            tables = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
            for (table,) in tables:
                columns = [
                    row[0]
                    for row in con.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = ?
                        ORDER BY ordinal_position
                        """,
                        [table],
                    ).fetchall()
                ]
                key = f"{label}.{table}"
                table_columns[key] = columns
                hits = [
                    column
                    for column in columns
                    if any(token in column.lower() for token in ["div", "dvd", "bonus", "payout"])
                ]
                count = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                rows.append({"数据源": label, "表": table, "行数": count, "分红相关字段": ", ".join(hits) or "-"})
    return audit_dividend_data_sources(table_columns), pd.DataFrame(rows)


def create_dividend_quality_asof_table(con) -> None:
    """构造红利质量 as-of 年报快照，禁止使用未来分红信息。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE dividend_quality_asof AS
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
                f.ts_code AS symbol,
                f.end_date,
                p.f_ann_date,
                CAST(f.roe AS DOUBLE) AS roe,
                CAST(f.roa AS DOUBLE) AS roa,
                CAST(f.ocf_to_or AS DOUBLE) AS ocf_to_or,
                CAST(f.debt_to_assets AS DOUBLE) AS debt_to_assets,
                CAST(b.total_share AS DOUBLE) AS total_share,
                CAST(i.n_income_attr_p AS DOUBLE) AS net_profit_parent,
                CAST(i.comshare_payable_dvd AS DOUBLE) AS common_dividend_payable,
                CAST(i.div_payt AS DOUBLE) AS dividend_paid_proxy
            FROM fina_db.default_table f
            JOIN publish_dates p ON f.ts_code = p.ts_code AND f.end_date = p.end_date
            LEFT JOIN balance_db.default_table b ON f.ts_code = b.ts_code AND f.end_date = b.end_date
            LEFT JOIN income_db.default_table i ON f.ts_code = i.ts_code AND f.end_date = i.end_date
            WHERE RIGHT(f.end_date, 4) = '1231'
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


def load_dividend_quality_candidates(con) -> pd.DataFrame:
    """读取满足可交易条件且有 as-of 红利代理数据的候选池。"""
    frame = con.execute(
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
            q.total_share,
            q.net_profit_parent,
            q.common_dividend_payable,
            q.dividend_paid_proxy,
            COALESCE(q.common_dividend_payable, q.dividend_paid_proxy) AS dividend_amount_proxy,
            CASE WHEN f.close * q.total_share > 0
                 THEN COALESCE(q.common_dividend_payable, q.dividend_paid_proxy) / (f.close * q.total_share)
            END AS dividend_yield_proxy,
            CASE WHEN q.net_profit_parent > 0
                 THEN COALESCE(q.common_dividend_payable, q.dividend_paid_proxy) / q.net_profit_parent
            END AS payout_ratio
        FROM features f
        JOIN dividend_quality_asof q ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()
    if frame.empty:
        frame["dividend_consistency"] = []
        return frame
    return add_dividend_consistency(frame)


def add_dividend_consistency(frame: pd.DataFrame) -> pd.DataFrame:
    """按已披露年报估算最近三期连续分红次数。"""
    data = frame.copy()
    data["dividend_consistency"] = 0
    for symbol, group in data.groupby("symbol", sort=False):
        ordered = group.sort_values(["signal_date", "end_date"]).copy()
        positive = ordered["dividend_amount_proxy"].fillna(0).astype(float) > 0
        rolling = positive.rolling(3, min_periods=1).sum().astype(int)
        data.loc[ordered.index, "dividend_consistency"] = rolling.values
    return data


def apply_dividend_quality_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """基础清洗：上市满3年、剔除ST/退市、必须有分红、约束支付率和负债率。"""
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
        & (pd.to_numeric(data["dividend_yield_proxy"], errors="coerce") > 0)
        & pd.to_numeric(data["payout_ratio"], errors="coerce").between(0, 1.2, inclusive="both")
        & (pd.to_numeric(data["debt_to_assets"], errors="coerce") <= 85)
        & data[["roe", "roa", "ocf_to_or"]].notna().all(axis=1)
    )
    data = data[valid].copy()
    if data.empty:
        return data
    kept = []
    for _, group in data.groupby("signal_date", sort=True):
        dividend = pd.to_numeric(group["dividend_yield_proxy"], errors="coerce")
        payout = pd.to_numeric(group["payout_ratio"], errors="coerce")
        filtered = group[
            dividend.between(dividend.quantile(0.02), dividend.quantile(0.98), inclusive="both")
            & payout.between(payout.quantile(0.02), payout.quantile(0.98), inclusive="both")
        ]
        kept.append(filtered)
    return pd.concat(kept, ignore_index=True) if kept else data.iloc[0:0].copy()


def score_dividend_quality_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """40%股息率、30%质量、30%现金流质量打分。"""
    scored = frame.dropna(subset=DIVIDEND_COLUMNS).copy()
    scored["dividend_yield_z"] = _zscore(_winsorize(scored["dividend_yield_proxy"]))
    scored["roe_z"] = _zscore(_winsorize(scored["roe"]))
    scored["roa_z"] = _zscore(_winsorize(scored["roa"]))
    scored["ocf_to_or_z"] = _zscore(_winsorize(scored["ocf_to_or"]))
    scored["quality_component"] = scored[["roe_z", "roa_z"]].mean(axis=1)
    scored["cashflow_component"] = scored["ocf_to_or_z"]
    scored["dividend_quality_score"] = (
        0.4 * scored["dividend_yield_z"]
        + 0.3 * scored["quality_component"]
        + 0.3 * scored["cashflow_component"]
    )
    return scored.sort_values(["dividend_quality_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_dividend_quality_selections(candidates: pd.DataFrame) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """月频 Top20 等权股票池。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        top = score_dividend_quality_frame(group).head(20).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    if not holdings:
        return selections, pd.DataFrame()
    return selections, pd.concat(holdings, ignore_index=True)


def add_industry_and_size(holdings: pd.DataFrame) -> pd.DataFrame:
    """补充行业和市值分层。"""
    manager = IndustryManager()
    enriched = holdings.copy()
    enriched["industry_level1"] = [
        manager.get_industry_by_stock(symbol).get("level1", "未知") for symbol in enriched["symbol"]
    ]
    enriched["market_cap_proxy"] = enriched["close"] * enriched["total_share"]
    enriched["market_cap_bucket"] = "未知"
    for signal_date, group in enriched.groupby("signal_date", sort=True):
        try:
            labels = pd.qcut(group["market_cap_proxy"], 4, labels=["小盘", "中小盘", "中大盘", "大盘"])
        except ValueError:
            labels = pd.Series(["未知"] * len(group), index=group.index)
        enriched.loc[group.index, "market_cap_bucket"] = labels.astype(str).values
    return enriched


def summarize_distribution(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """汇总持仓分布。"""
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, "持仓记录数", "占比"])
    grouped = frame.groupby(column).size().reset_index(name="持仓记录数")
    grouped["占比"] = grouped["持仓记录数"] / len(frame)
    return grouped.sort_values("持仓记录数", ascending=False)


def build_coverage_report(raw: pd.DataFrame, filtered: pd.DataFrame) -> pd.DataFrame:
    """按调仓日输出分红代理覆盖度。"""
    rows = []
    for signal_date, group in raw.groupby("signal_date", sort=True):
        with_dividend = group["dividend_yield_proxy"].notna() & (group["dividend_yield_proxy"] > 0)
        rows.append(
            {
                "signal_date": signal_date,
                "候选样本": len(group),
                "有分红代理样本": int(with_dividend.sum()),
                "清洗后样本": int((filtered["signal_date"] == signal_date).sum()) if not filtered.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def add_calmar(metrics: pd.DataFrame) -> pd.DataFrame:
    """补充 Calmar。"""
    result = metrics.copy()
    result["Calmar"] = result.apply(
        lambda row: row["年化收益"] / abs(row["最大回撤"]) if row["最大回撤"] < 0 else 0.0,
        axis=1,
    )
    return result


def run_study() -> None:
    """运行完整 Dividend Quality V1 研究。"""
    audit, source_coverage = inspect_local_dividend_sources()
    import duckdb

    with duckdb.connect(":memory:") as con:
        con.execute(f"ATTACH DATABASE '{DB_PATH}' AS main_db (READ_ONLY)")
        for table in ["daily", "daily_adj_cache", "stock_basic", "stock_st", "stock_namechange", "stock_name_manual"]:
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM main_db.{table}")
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_dividend_quality_asof_table(con)
        raw_candidates = load_dividend_quality_candidates(con)
        filtered = apply_dividend_quality_filters(raw_candidates)
        selections, holdings = build_dividend_quality_selections(filtered)
        create_annual_financial_asof_table(con)
        quality_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        quality_selections, _ = build_top20_from_candidates(quality_candidates)
        holdings = add_stock_basic(holdings, con)
        holdings = add_industry_and_size(holdings)
        coverage = build_coverage_report(raw_candidates, filtered)
        all_symbols = sorted(set(holdings["symbol"].tolist()) | {s for symbols in quality_selections.values() for s in symbols})
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        benchmark, _ = load_hs300_benchmark(
            con,
            "20150101",
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        dividend_result = run_monthly_backtest(
            "Dividend Quality V1",
            selections,
            bars,
            calendar,
            ExecutionModel(slippage_bps=5.0),
        )
        quality_result = run_monthly_backtest(
            "Quality Alpha V1",
            quality_selections,
            bars,
            calendar,
            ExecutionModel(slippage_bps=5.0),
        )
        metrics = add_calmar(build_metrics_table({
            "Dividend Quality V1": dividend_result,
            "Quality Alpha V1": quality_result,
        }, benchmark))
    latest_date = max(holdings["signal_date"]) if not holdings.empty else ""
    latest_holdings = holdings[holdings["signal_date"].eq(latest_date)].sort_values("rank") if latest_date else holdings
    industry_dist = summarize_distribution(holdings, "industry_level1")
    size_dist = summarize_distribution(holdings, "market_cap_bucket")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        render_dividend_quality_report(audit, source_coverage, coverage, metrics, industry_dist, size_dist, latest_holdings),
        encoding="utf-8",
    )
    print(REPORT_PATH.read_text(encoding="utf-8"))


def _winsorize(series: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.clip(numeric.quantile(lower), numeric.quantile(upper))


def _zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    std = numeric.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (numeric - numeric.mean()) / std


if __name__ == "__main__":
    run_study()
