"""
低波动策略收益来源归因研究。

使用本地日线行情与 fina_indicator 财务数据，按公告日 as-of 比较低波动组合
和全市场可投 universe 的质量暴露，判断低波动收益来源。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DAILY_DB = Path("daily_adj_19901219_20260615.duckdb")
FINA_DB = Path("fina_indicator.duckdb")
REPORT_PATH = Path("reports/low_vol_attribution_study.md")
START_DATE = "20150101"
LOOKBACK_START = "20140701"
FIELDS = ["roe", "roa", "grossprofit_margin", "tr_yoy", "debt_to_assets"]


def main() -> None:
    """运行低波动归因研究并生成报告。"""
    import duckdb

    if not DAILY_DB.exists() or not FINA_DB.exists():
        raise FileNotFoundError("缺少 daily_adj 或 fina_indicator DuckDB 数据文件")
    con = duckdb.connect(str(DAILY_DB), read_only=True)
    try:
        con.execute(f"ATTACH DATABASE '{FINA_DB}' AS fina_db (READ_ONLY)")
        create_low_vol_tables(con)
        exposure = load_exposure(con)
        returns = load_forward_returns(con)
        summary = summarize_exposure(exposure)
        return_summary = summarize_returns(returns)
        low_avg = summary[summary["bucket"] == "low_vol"].set_index("metric")["mean"]
        market_avg = summary[summary["bucket"] == "market"].set_index("metric")["mean"]
        spreads = quality_spread(low_avg, market_avg)
        quality_score = calculate_quality_score(spreads)
        decision = classify_attribution(
            excess_return=float(return_summary.loc["excess", "annual_return"]),
            low_vol_realized_vol=float(return_summary.loc["low_vol", "realized_vol"]),
            market_realized_vol=float(return_summary.loc["market", "realized_vol"]),
            quality_score=quality_score,
        )
        report = render_report(summary, spreads, return_summary, quality_score, decision)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(report)
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


def create_low_vol_tables(con) -> None:
    """创建低波组合、全市场 universe 和 as-of 财务暴露临时表。"""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE monthly_universe AS
        WITH bars AS (
          SELECT a.ts_code AS symbol, a.trade_date, a.close_qfq AS close, d.vol AS volume,
                 d.amount, st.name AS st_name,
                 LAG(a.close_qfq) OVER(PARTITION BY a.ts_code ORDER BY a.trade_date) AS prev_close
          FROM daily_adj_cache a
          JOIN daily d ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
          LEFT JOIN stock_st st ON a.ts_code = st.ts_code AND a.trade_date = st.trade_date
          WHERE a.trade_date >= '{LOOKBACK_START}'
        ),
        feats AS (
          SELECT *, close / NULLIF(prev_close, 0) - 1 AS ret
          FROM bars
        ),
        scored AS (
          SELECT *,
                 STDDEV_SAMP(ret) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS vol60,
                 QUANTILE_CONT(amount, 0.2) OVER(PARTITION BY trade_date) AS amount_p20,
                 MAX(trade_date) OVER(PARTITION BY SUBSTR(trade_date, 1, 6)) AS month_end
          FROM feats
        )
        SELECT symbol, trade_date AS signal_date, close, vol60, amount, volume
        FROM scored
        WHERE trade_date = month_end
          AND trade_date >= '{START_DATE}'
          AND st_name IS NULL
          AND volume > 0
          AND amount > amount_p20
          AND vol60 IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE low_vol_selection AS
        SELECT *
        FROM (
          SELECT *, ROW_NUMBER() OVER(PARTITION BY signal_date ORDER BY vol60 ASC) AS low_vol_rank
          FROM monthly_universe
        )
        WHERE low_vol_rank <= 20
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE financial_asof AS
        WITH base AS (
          SELECT ts_code AS symbol, end_date, ann_date AS publish_date,
                 roe, roa, grossprofit_margin, tr_yoy, debt_to_assets
          FROM fina_db.default_table
          WHERE ann_date IS NOT NULL
        ),
        joined AS (
          SELECT u.signal_date, u.symbol, b.end_date, b.publish_date,
                 b.roe, b.roa, b.grossprofit_margin, b.tr_yoy, b.debt_to_assets,
                 ROW_NUMBER() OVER(
                   PARTITION BY u.signal_date, u.symbol
                   ORDER BY b.end_date DESC, b.publish_date DESC
                 ) AS rn
          FROM monthly_universe u
          LEFT JOIN base b
            ON u.symbol = b.symbol AND b.publish_date <= u.signal_date
        )
        SELECT * EXCLUDE (rn)
        FROM joined
        WHERE rn = 1
        """
    )


def load_exposure(con) -> pd.DataFrame:
    """读取低波组合与全市场 as-of 财务暴露。"""
    parts = []
    for bucket, table in [("low_vol", "low_vol_selection"), ("market", "monthly_universe")]:
        frame = con.execute(
            f"""
            SELECT '{bucket}' AS bucket, f.signal_date, f.symbol,
                   f.roe, f.roa, f.grossprofit_margin, f.tr_yoy, f.debt_to_assets
            FROM "{table}" s
            JOIN financial_asof f
              ON s.signal_date = f.signal_date AND s.symbol = f.symbol
            """
        ).fetchdf()
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


def load_forward_returns(con) -> pd.DataFrame:
    """读取低波组合和市场 universe 的下一月收益。"""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE next_month_returns AS
        WITH dates AS (
          SELECT signal_date,
                 LEAD(signal_date) OVER(ORDER BY signal_date) AS next_signal_date
          FROM (SELECT DISTINCT signal_date FROM monthly_universe)
        ),
        universe_ret AS (
          SELECT u.signal_date, u.symbol, n.next_signal_date,
                 u.close AS start_close, e.close_qfq AS end_close
          FROM monthly_universe u
          JOIN dates n ON u.signal_date = n.signal_date
          JOIN daily_adj_cache e ON u.symbol = e.ts_code AND e.trade_date = n.next_signal_date
          WHERE n.next_signal_date IS NOT NULL
        )
        SELECT signal_date, symbol, end_close / NULLIF(start_close, 0) - 1 AS forward_return
        FROM universe_ret
        """
    )
    low = con.execute(
        """
        SELECT 'low_vol' AS bucket, r.signal_date, AVG(r.forward_return) AS monthly_return
        FROM next_month_returns r
        JOIN low_vol_selection s ON r.signal_date = s.signal_date AND r.symbol = s.symbol
        GROUP BY r.signal_date
        """
    ).fetchdf()
    market = con.execute(
        """
        SELECT 'market' AS bucket, signal_date, AVG(forward_return) AS monthly_return
        FROM next_month_returns
        GROUP BY signal_date
        """
    ).fetchdf()
    return pd.concat([low, market], ignore_index=True)


def summarize_exposure(exposure: pd.DataFrame) -> pd.DataFrame:
    """计算组合平均质量指标。"""
    rows = []
    for bucket, group in exposure.groupby("bucket"):
        for field in FIELDS:
            rows.append({"bucket": bucket, "metric": field, "mean": float(pd.to_numeric(group[field], errors="coerce").mean())})
    return pd.DataFrame(rows)


def summarize_returns(returns: pd.DataFrame) -> pd.DataFrame:
    """计算低波、市场和超额收益统计。"""
    rows = []
    pivot = returns.pivot(index="signal_date", columns="bucket", values="monthly_return").dropna()
    for bucket in ["low_vol", "market"]:
        series = pivot[bucket].astype(float)
        rows.append({"bucket": bucket, "annual_return": annualized_return(series), "realized_vol": float(series.std() * (12 ** 0.5))})
    excess = pivot["low_vol"].astype(float) - pivot["market"].astype(float)
    rows.append({"bucket": "excess", "annual_return": annualized_return(excess), "realized_vol": float(excess.std() * (12 ** 0.5))})
    return pd.DataFrame(rows).set_index("bucket")


def annualized_return(monthly_returns: pd.Series) -> float:
    """月收益年化。"""
    if monthly_returns.empty:
        return 0.0
    total = float((1 + monthly_returns).prod() - 1)
    return float((1 + total) ** (12 / len(monthly_returns)) - 1)


def quality_spread(low_vol: pd.Series, market: pd.Series) -> dict[str, float]:
    """计算低波组合相对全市场的质量暴露差异。"""
    spread = {field: float(low_vol.get(field, float("nan")) - market.get(field, float("nan"))) for field in FIELDS}
    spread["debt_to_assets_quality"] = -spread["debt_to_assets"]
    return spread


def calculate_quality_score(spread: dict[str, float]) -> float:
    """把质量暴露方向压成简单得分。"""
    positives = [
        spread.get("roe", 0) > 0,
        spread.get("roa", 0) > 0,
        spread.get("grossprofit_margin", 0) > 0,
        spread.get("tr_yoy", 0) > 0,
        spread.get("debt_to_assets_quality", 0) > 0,
    ]
    return sum(1 for item in positives if item) / len(positives)


def classify_attribution(
    excess_return: float,
    low_vol_realized_vol: float,
    market_realized_vol: float,
    quality_score: float,
) -> str:
    """判断低波收益来源。"""
    risk_premium = excess_return > 0 and low_vol_realized_vol < market_realized_vol
    quality_exposure = quality_score >= 0.6
    if risk_premium and quality_exposure:
        return "C. 低波动风险溢价与高质量公司暴露共同作用"
    if risk_premium:
        return "A. 主要来自低波动风险溢价"
    if quality_exposure:
        return "B. 主要来自高质量公司暴露"
    return "未观察到稳定低波动风险溢价或高质量暴露"


def render_report(summary: pd.DataFrame, spreads: dict[str, float], returns: pd.DataFrame, quality_score: float, decision: str) -> str:
    """渲染归因报告。"""
    table = summary.pivot(index="metric", columns="bucket", values="mean").reset_index()
    table["spread_low_vol_minus_market"] = table["metric"].map(lambda metric: spreads.get(metric, float("nan")))
    lines = [
        "# Low Vol Attribution Study",
        "",
        f"- 数据：`{DAILY_DB}` + `{FINA_DB}`",
        "- 财务可见性：使用 `ann_date <= signal_date` 的 as-of 口径",
        "- 组合：月末全市场可投股票中，60日收益标准差最低20只",
        "",
        "## 组合平均质量指标",
        "",
        markdown_table(format_table(table)),
        "",
        "## 收益与波动",
        "",
        markdown_table(format_return_table(returns.reset_index())),
        "",
        "## 归因判断",
        "",
        f"- 质量暴露得分：{quality_score:.2f}",
        f"- 结论：{decision}",
        "",
    ]
    return "\n".join(lines)


def format_table(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化质量指标表。"""
    result = frame.copy()
    for column in result.columns:
        if column != "metric":
            result[column] = result[column].map(lambda value: "N/A" if pd.isna(value) else f"{value:.2f}")
    return result


def format_return_table(frame: pd.DataFrame) -> pd.DataFrame:
    """格式化收益表。"""
    result = frame.copy()
    for column in ["annual_return", "realized_vol"]:
        result[column] = result[column].map(lambda value: f"{value:.2%}")
    return result


def markdown_table(frame: pd.DataFrame) -> str:
    """生成 Markdown 表格。"""
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
