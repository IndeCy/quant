"""
Cash Cow V1 研究。

目标：验证经营现金流真实、扣除资本开支后仍能创造自由现金流的公司，
是否能成为 Quality Alpha V1 之外的第二条基本面主线。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.cash_cow_report import (
    add_exposures,
    calculate_calmar,
    drawdown_window,
    monthly_win_loss,
    render_cash_cow_report,
    return_correlation,
    summarize_distribution,
    summarize_factor_distribution,
    worst_contributors,
)
from backtest.execution_model import ExecutionModel
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
    START_DATE,
    build_metrics_table,
    create_feature_table,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/cash_cow_v1.md")
HOLDINGS_PATH = Path("reports/cash_cow_v1_holdings.csv")
CASH_COW_COLUMNS = ["ocf_to_or", "ocf_to_np", "fcf_to_assets"]


def compute_cash_cow_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """构造 Cash Cow 原始字段，资本开支使用购建长期资产支付现金。"""
    data = frame.copy()
    ocf = pd.to_numeric(data["n_cashflow_act"], errors="coerce")
    capex = pd.to_numeric(data["c_pay_acq_const_fiolta"], errors="coerce")
    revenue = pd.to_numeric(data["revenue"], errors="coerce")
    net_profit = pd.to_numeric(data["n_income_attr_p"], errors="coerce")
    assets = pd.to_numeric(data["total_assets"], errors="coerce")
    data["ocf_to_or_raw"] = ocf / revenue.replace(0, pd.NA)
    data["ocf_to_np"] = ocf / net_profit.replace(0, pd.NA)
    data["fcf"] = ocf - capex
    data["fcf_to_assets"] = data["fcf"] / assets.replace(0, pd.NA)
    return data


def score_cash_cow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """固定 35/35/30 权重计算 CashCowScore。"""
    scored = frame.dropna(subset=CASH_COW_COLUMNS).copy()
    for column in CASH_COW_COLUMNS:
        scored[f"{column}_z"] = _zscore(_winsorize(scored[column]))
    scored["cash_cow_score"] = (
        0.35 * scored["ocf_to_or_z"]
        + 0.35 * scored["ocf_to_np_z"]
        + 0.30 * scored["fcf_to_assets_z"]
    )
    return scored.sort_values(["cash_cow_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def calculate_overlap(first: dict[str, list[str]], second: dict[str, list[str]]) -> float:
    """计算两个策略按月 TopN 持仓平均重叠比例。"""
    overlaps = []
    for date in sorted(set(first) & set(second)):
        a = set(first[date])
        b = set(second[date])
        if a and b:
            overlaps.append(len(a & b) / min(len(a), len(b)))
    return float(pd.Series(overlaps).mean()) if overlaps else 0.0


def create_cash_cow_asof_table(con) -> None:
    """构造只使用 1231 年报的 Cash Cow as-of 表。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE financial_cash_cow_asof AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS f_ann_date
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, ann_date AS f_ann_date FROM fina_db.default_table WHERE ann_date IS NOT NULL
            )
            WHERE RIGHT(end_date, 4) = '1231'
            GROUP BY ts_code, end_date
        ),
        raw AS (
            SELECT
                p.ts_code AS symbol,
                p.end_date,
                p.f_ann_date,
                CAST(f.ocf_to_or AS DOUBLE) AS ocf_to_or,
                CAST(f.debt_to_assets AS DOUBLE) AS debt_to_assets,
                CAST(i.revenue AS DOUBLE) AS revenue,
                CAST(i.n_income_attr_p AS DOUBLE) AS n_income_attr_p,
                CAST(b.total_assets AS DOUBLE) AS total_assets,
                CAST(b.total_liab AS DOUBLE) AS total_liab,
                CAST(c.n_cashflow_act AS DOUBLE) AS n_cashflow_act,
                CAST(c.c_pay_acq_const_fiolta AS DOUBLE) AS c_pay_acq_const_fiolta,
                CAST(c.free_cashflow AS DOUBLE) AS provider_free_cashflow
            FROM publish_dates p
            JOIN fina_db.default_table f ON p.ts_code = f.ts_code AND p.end_date = f.end_date
            JOIN income_db.default_table i ON p.ts_code = i.ts_code AND p.end_date = i.end_date
            JOIN balance_db.default_table b ON p.ts_code = b.ts_code AND p.end_date = b.end_date
            JOIN cashflow_db.default_table c ON p.ts_code = c.ts_code AND p.end_date = c.end_date
            WHERE p.f_ann_date IS NOT NULL
        ),
        scored AS (
            SELECT
                *,
                n_cashflow_act / NULLIF(n_income_attr_p, 0) AS ocf_to_np,
                n_cashflow_act - c_pay_acq_const_fiolta AS fcf,
                (n_cashflow_act - c_pay_acq_const_fiolta) / NULLIF(total_assets, 0) AS fcf_to_assets,
                total_liab / NULLIF(total_assets, 0) * 100 AS debt_to_assets_raw,
                ABS((n_cashflow_act - c_pay_acq_const_fiolta) - provider_free_cashflow) AS fcf_vendor_abs_diff
            FROM raw
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
            JOIN scored q ON q.f_ann_date <= d.signal_date
        )
        SELECT *
        FROM ranked
        WHERE rn = 1
        """
    )


def audit_cash_cow_fields(con) -> pd.DataFrame:
    """审计 Cash Cow 所需财务字段覆盖率、起始时间和极端值。"""
    source_map = [
        ("OCF_TO_OR", "fina_db", "fina_indicator", "ocf_to_or", "经营现金流/营业收入"),
        ("OCF_TO_NP分子", "cashflow_db", "cashflow", "n_cashflow_act", "经营活动现金流净额"),
        ("OCF_TO_NP分母", "income_db", "income", "n_income_attr_p", "归母净利润"),
        ("FCF资本开支", "cashflow_db", "cashflow", "c_pay_acq_const_fiolta", "购建固定资产等长期资产支付现金"),
        ("FCF供应商口径", "cashflow_db", "cashflow", "free_cashflow", "Tushare free_cashflow参考"),
        ("FCF_TO_ASSETS分母", "balance_db", "balancesheet", "total_assets", "总资产"),
        ("资产负债率", "fina_db", "fina_indicator", "debt_to_assets", "资产负债率"),
    ]
    rows = []
    for factor, alias, schema, column, note in source_map:
        table = f"{alias}.default_table"
        date_expr = "ann_date" if schema == "fina_indicator" else "f_ann_date"
        stats = con.execute(
            f"""
            SELECT
                MIN(end_date), MAX(end_date),
                MIN({date_expr}), MAX({date_expr}),
                COUNT(*),
                SUM(CASE WHEN {column} IS NULL THEN 1 ELSE 0 END),
                QUANTILE_CONT(CAST({column} AS DOUBLE), 0.01),
                QUANTILE_CONT(CAST({column} AS DOUBLE), 0.99)
            FROM {table}
            WHERE RIGHT(end_date, 4) = '1231'
            """
        ).fetchone()
        total = int(stats[4] or 0)
        missing = int(stats[5] or 0)
        rows.append(
            {
                "字段": factor,
                "来源表": schema,
                "字段名": column,
                "说明": note,
                "可用起始报告期": stats[0],
                "可用结束报告期": stats[1],
                "披露日起点": stats[2],
                "披露日终点": stats[3],
                "缺失率": missing / total if total else 1.0,
                "P1": stats[6],
                "P99": stats[7],
                "严格asof": "是",
            }
        )
    return pd.DataFrame(rows)


def load_cash_cow_candidates(con) -> pd.DataFrame:
    """读取 Cash Cow 候选池，叠加交易、上市、ST过滤所需字段。"""
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
            q.ocf_to_or,
            q.ocf_to_np,
            q.fcf,
            q.fcf_to_assets,
            q.debt_to_assets,
            q.debt_to_assets_raw,
            q.provider_free_cashflow,
            q.fcf_vendor_abs_diff
        FROM features f
        JOIN financial_cash_cow_asof q ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        LEFT JOIN name_asof na ON f.trade_date = na.signal_date AND f.symbol = na.symbol AND na.rn = 1
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def apply_cash_cow_filters(frame: pd.DataFrame) -> pd.DataFrame:
    """执行基础股票池清洗和资产负债率负向约束。"""
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
        & data[CASH_COW_COLUMNS + ["debt_to_assets"]].notna().all(axis=1)
    )
    data = data[valid].copy()
    kept = []
    for _, group in data.groupby("signal_date", sort=True):
        cap = group["debt_to_assets"].quantile(0.80)
        kept.append(group[group["debt_to_assets"] <= cap])
    return pd.concat(kept, ignore_index=True) if kept else data.iloc[0:0].copy()


def build_cash_cow_selections(candidates: pd.DataFrame) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按 CashCowScore 选 Top20。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_cash_cow_frame(group)
        top = scored.head(20).copy()
        top["signal_date"] = str(signal_date)
        top["rank"] = range(1, len(top) + 1)
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    return selections, pd.concat(holdings, ignore_index=True) if holdings else pd.DataFrame()


def main() -> None:
    """运行 Cash Cow V1 审计、回测和法医分析。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        audit = audit_cash_cow_fields(con)
        create_cash_cow_asof_table(con)
        raw = load_cash_cow_candidates(con)
        candidates = apply_cash_cow_filters(raw)
        cash_selections, cash_holdings = build_cash_cow_selections(candidates)
        if cash_holdings.empty:
            raise RuntimeError("Cash Cow V1 没有可用持仓")
        cash_holdings = add_exposures(cash_holdings)

        create_annual_financial_asof_table(con)
        quality_candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        quality_selections, _ = build_top20_from_candidates(quality_candidates)

        all_symbols = sorted({symbol for symbols in cash_selections.values() for symbol in symbols})
        quality_symbols = sorted({symbol for symbols in quality_selections.values() for symbol in symbols})
        bars = load_research_bars(con, sorted(set(all_symbols) | set(quality_symbols)))
        calendar = load_calendar(con)
        execution_model = ExecutionModel(slippage_bps=5.0)
        cash_result = run_monthly_backtest("Cash Cow V1", cash_selections, bars, calendar, execution_model)
        quality_result = run_monthly_backtest("Quality Alpha V1", quality_selections, bars, calendar, execution_model)
        benchmark, benchmark_label = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        metrics = build_metrics_table({"Cash Cow V1": cash_result, "Quality Alpha V1": quality_result}, benchmark)
        metrics["Calmar"] = [calculate_calmar(cash_result.daily_values), calculate_calmar(quality_result.daily_values)]
        factor_dist = summarize_factor_distribution(cash_holdings)
        industry = summarize_distribution(cash_holdings, "industry_level1")
        size_dist = summarize_distribution(cash_holdings, "market_cap_bucket")
        dd = drawdown_window(cash_result.daily_values)
        worst = worst_contributors(cash_result, cash_holdings)
        overlap = calculate_overlap(cash_selections, quality_selections)
        corr = return_correlation(cash_result.daily_values, quality_result.daily_values)
        wins = monthly_win_loss(cash_result.daily_values, quality_result.daily_values)
        report = render_cash_cow_report(audit, metrics, factor_dist, industry, size_dist, dd, worst, overlap, corr, wins)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        cash_holdings.to_csv(HOLDINGS_PATH, index=False)
        print(metrics.to_string(index=False))
        print(f"基准: {benchmark_label}")
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


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
    main()
