"""
Quality Strategy V1 研究脚本。

策略目标：只使用本地 DuckDB 行情和财务数据，基于 f_ann_date as-of
构造 ROE、ROA、经营现金流质量三因子 Top20 月频组合。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.research_benchmark import load_hs300_benchmark
from examples.strategy_comparison_research import (
    START_DATE,
    build_metrics_table,
    create_feature_table,
    format_percent,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)


DB_PATH = Path("daily_adj_19901219_20260615.duckdb")
FINA_PATH = Path("fina_indicator.duckdb")
INCOME_PATH = Path("income.duckdb")
BALANCE_PATH = Path("balancesheet.duckdb")
CASHFLOW_PATH = Path("cashflow.duckdb")
FUND_DAILY_PATH = Path("etf_lof_reits_daily_adj_20041220_20260617.duckdb")
FUND_BASIC_PATH = Path("etf_lof_reits_basic_export_20041220_20260617.duckdb")
REPORT_PATH = Path("reports/quality_strategy_v1.md")
QUALITY_COLUMNS = ["roe", "roa", "ocf_to_or"]
ATTRIBUTION_COLUMNS = ["roe", "roa", "debt_to_assets", "tr_yoy"]


def winsorize_series(series: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    """对单个横截面因子做分位数缩尾，降低极端财务值影响。"""
    numeric = pd.to_numeric(series, errors="coerce")
    lower_bound = numeric.quantile(lower)
    upper_bound = numeric.quantile(upper)
    return numeric.clip(lower_bound, upper_bound)


def zscore_series(series: pd.Series) -> pd.Series:
    """对单个横截面因子做 Z-score 标准化。"""
    numeric = pd.to_numeric(series, errors="coerce")
    std = numeric.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (numeric - numeric.mean()) / std


def score_quality_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """计算 ROE、ROA、经营现金流质量三因子等权分数。"""
    scored = frame.dropna(subset=QUALITY_COLUMNS).copy()
    for column in QUALITY_COLUMNS:
        # 先缩尾再标准化，避免单个异常财报指标主导选股。
        scored[f"{column}_z"] = zscore_series(winsorize_series(scored[column]))
    scored["quality_score"] = scored[[f"{column}_z" for column in QUALITY_COLUMNS]].mean(axis=1)
    return scored.sort_values(["quality_score", "symbol"], ascending=[False, True]).reset_index(drop=True)


def attach_financial_dbs(con) -> None:
    """挂载财务库，后续 SQL 统一从 f_ann_date 做 as-of。"""
    for path in [FINA_PATH, INCOME_PATH, BALANCE_PATH, CASHFLOW_PATH]:
        if not path.exists():
            raise FileNotFoundError(f"缺少财务 DuckDB 数据文件: {path.resolve()}")
    con.execute(f"ATTACH DATABASE '{FINA_PATH}' AS fina_db (READ_ONLY)")
    con.execute(f"ATTACH DATABASE '{INCOME_PATH}' AS income_db (READ_ONLY)")
    con.execute(f"ATTACH DATABASE '{BALANCE_PATH}' AS balance_db (READ_ONLY)")
    con.execute(f"ATTACH DATABASE '{CASHFLOW_PATH}' AS cashflow_db (READ_ONLY)")


def create_signal_date_table(con, signal_dates: list[str]) -> None:
    """把月末调仓日写成临时表，便于 as-of SQL join。"""
    con.execute("CREATE OR REPLACE TEMP TABLE quality_signal_dates(signal_date VARCHAR)")
    con.executemany("INSERT INTO quality_signal_dates VALUES (?)", [(date,) for date in signal_dates])


def create_financial_asof_table(con) -> None:
    """构造严格按 f_ann_date 截止的财务因子快照。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE financial_quality_asof AS
        WITH publish_dates AS (
            SELECT ts_code, end_date, MAX(f_ann_date) AS f_ann_date
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
            )
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


def load_quality_candidates(con) -> pd.DataFrame:
    """读取每个调仓日可交易且已有披露财务数据的候选池。"""
    return con.execute(
        """
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            f.close,
            q.end_date,
            q.f_ann_date,
            q.roe,
            q.roa,
            q.ocf_to_or,
            q.debt_to_assets,
            q.tr_yoy
        FROM features f
        JOIN financial_quality_asof q ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
          AND f.st_name IS NULL
          AND f.amount > f.amount_p20
          AND f.volume > 0
          AND f.close > 0
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_quality_selections(candidates: pd.DataFrame) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """按月横截面评分并选出 Top20。"""
    selections: dict[str, list[str]] = {}
    holdings = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        scored = score_quality_frame(group)
        top = scored.head(20).copy()
        selections[str(signal_date)] = top["symbol"].tolist()
        holdings.append(top)
    if not holdings:
        return selections, pd.DataFrame()
    return selections, pd.concat(holdings, ignore_index=True)


def build_attribution_table(holdings: pd.DataFrame) -> pd.DataFrame:
    """汇总组合平均质量暴露。"""
    rows = []
    labels = {
        "roe": "ROE",
        "roa": "ROA",
        "debt_to_assets": "资产负债率",
        "tr_yoy": "营收增长率",
    }
    for column in ATTRIBUTION_COLUMNS:
        rows.append({"指标": labels[column], "组合平均": float(holdings[column].mean())})
    return pd.DataFrame(rows)


def render_report(metrics: pd.DataFrame, attribution: pd.DataFrame, benchmark_label: str, latest_date: str) -> str:
    """渲染 Markdown 研究报告。"""
    formatted_metrics = metrics.copy()
    for column in ["年化收益", "最大回撤", "年化换手率", "执行成本影响", "总收益", "基准收益", "超额收益"]:
        formatted_metrics[column] = formatted_metrics[column].map(format_percent)
    formatted_metrics["夏普比率"] = formatted_metrics["夏普比率"].map(lambda value: f"{value:.2f}")
    formatted_attribution = attribution.copy()
    formatted_attribution["组合平均"] = formatted_attribution["组合平均"].map(lambda value: f"{value:.2f}")
    return f"""# Quality Strategy V1 研究报告

## 策略定义

- 研究区间：2015-01-01 至 {latest_date}
- 数据口径：A 股前复权日线行情，财务指标来自本地财务 DuckDB。
- as-of 规则：所有财务指标必须满足 `f_ann_date <= 调仓信号日`。
- 因子：ROE、ROA、经营现金流质量（`ocf_to_or`，经营现金流 / 营业收入）。
- 处理流程：5%/95% Winsorize → Z-score → 三因子等权平均。
- 选股：剔除 ST、停牌、成交额最低 20%，每月最后一个交易日选 Top20。
- 执行：复用 M0 ExecutionModel，T 日信号，T+1 交易日开盘成交，滑点 5bps。
- 基准：{benchmark_label}

## 回测结果

{markdown_table(formatted_metrics)}

## 组合平均质量暴露

{markdown_table(formatted_attribution)}

## 结论

Quality Strategy V1 是一个高质量暴露组合，而不是收益优化后的参数策略。
当前版本只验证 ROE、ROA、经营现金流质量在真实披露日约束下的可回测性。
"""


def main() -> None:
    """运行 Quality Strategy V1 并写出研究报告。"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"缺少 DuckDB 行情数据文件: {DB_PATH.resolve()}")
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_financial_asof_table(con)
        candidates = load_quality_candidates(con)
        selections, holdings = build_quality_selections(candidates)
        all_symbols = sorted({symbol for symbols in selections.values() for symbol in symbols})
        bars = load_research_bars(con, all_symbols)
        calendar = load_calendar(con)
        execution_model = ExecutionModel(slippage_bps=5.0)
        result = run_monthly_backtest("Quality Strategy V1", selections, bars, calendar, execution_model)
        benchmark_curve, benchmark_label = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        metrics = build_metrics_table({"Quality Strategy V1": result}, benchmark_curve)
        attribution = build_attribution_table(holdings)
        latest_date = con.execute("SELECT MAX(trade_date) FROM features").fetchone()[0]
        report = render_report(metrics, attribution, benchmark_label, latest_date)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(metrics.to_string(index=False))
        print(attribution.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
