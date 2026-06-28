"""
Quality Strategy V1 审计脚本。

只做诊断，不改变因子、不优化收益、不修改执行层。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.industry import IndustryManager
from examples.quality_strategy_v1 import (
    BALANCE_PATH,
    CASHFLOW_PATH,
    DB_PATH,
    FINA_PATH,
    INCOME_PATH,
    QUALITY_COLUMNS,
    attach_financial_dbs,
    build_quality_selections,
    create_financial_asof_table,
    create_signal_date_table,
    score_quality_frame,
    winsorize_series,
)
from examples.strategy_comparison_research import (
    create_feature_table,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
    run_monthly_backtest,
)


REPORT_PATH = Path("reports/quality_strategy_v1_audit.md")
HOLDINGS_PATH = Path("reports/quality_strategy_v1_holdings.csv")
WORST_PATH = Path("reports/quality_strategy_v1_worst_contributors.csv")


def load_audit_candidates(con) -> pd.DataFrame:
    """读取审计候选池，保留过滤字段和上市信息。"""
    return con.execute(
        """
        SELECT
            f.trade_date AS signal_date,
            f.symbol,
            sb.name,
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
        JOIN financial_quality_asof q ON f.trade_date = q.signal_date AND f.symbol = q.symbol
        LEFT JOIN stock_basic sb ON f.symbol = sb.ts_code
        WHERE f.trade_date IN (SELECT signal_date FROM quality_signal_dates)
        ORDER BY f.trade_date, f.symbol
        """
    ).fetchdf()


def build_scored_holdings(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成每期评分明细和 Top20 持仓。"""
    scored_groups = []
    for signal_date, group in candidates.groupby("signal_date", sort=True):
        tradable = group[
            group["st_name"].isna()
            & (group["amount"] > group["amount_p20"])
            & (group["volume"] > 0)
            & (group["close"] > 0)
        ].copy()
        scored = score_quality_frame(tradable)
        for column in QUALITY_COLUMNS:
            scored[f"{column}_winsorized"] = winsorize_series(scored[column])
            scored[f"{column}_clipped"] = scored[column].ne(scored[f"{column}_winsorized"])
        scored["rank"] = range(1, len(scored) + 1)
        scored_groups.append(scored)
    scored_all = pd.concat(scored_groups, ignore_index=True)
    holdings = scored_all[scored_all["rank"] <= 20].copy()
    return scored_all, holdings


def add_audit_flags(holdings: pd.DataFrame) -> pd.DataFrame:
    """补充持仓审计标记。"""
    enriched = holdings.copy()
    signal_dt = pd.to_datetime(enriched["signal_date"], format="%Y%m%d")
    list_dt = pd.to_datetime(enriched["list_date"], format="%Y%m%d", errors="coerce")
    delist_dt = pd.to_datetime(enriched["delist_date"], format="%Y%m%d", errors="coerce")
    enriched["listed_years"] = (signal_dt - list_dt).dt.days / 365.25
    enriched["listed_lt_3y"] = enriched["listed_years"] < 3
    enriched["low_amount"] = enriched["amount"] <= enriched["amount_p20"]
    enriched["is_st"] = enriched["st_name"].notna()
    enriched["is_delisted_on_signal"] = delist_dt.notna() & (delist_dt <= signal_dt)
    enriched["name_contains_st_or_delist"] = enriched["name"].fillna("").str.contains("ST|退", regex=True)
    enriched["eventually_delisted"] = enriched["list_status"].fillna("").ne("L") | enriched["delist_date"].notna()
    enriched["future_function_violation"] = enriched["f_ann_date"] > enriched["signal_date"]
    enriched["report_period"] = enriched["end_date"].astype(str).str[-4:]
    return enriched


def add_industry(holdings: pd.DataFrame) -> pd.DataFrame:
    """使用项目内置行业树补充行业，覆盖不到的标为未知。"""
    manager = IndustryManager()
    enriched = holdings.copy()
    level1 = []
    level2 = []
    for symbol in enriched["symbol"]:
        info = manager.get_industry_by_stock(symbol)
        level1.append(info.get("level1", "未知"))
        level2.append(info.get("level2", "未知"))
    enriched["industry_level1"] = level1
    enriched["industry_level2"] = level2
    return enriched


def diagnose_financial_join(con) -> dict[str, int]:
    """检查 fina_indicator 与 f_ann_date 映射是否存在重复风险。"""
    fina_dup = con.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT ts_code, end_date, COUNT(*) AS cnt
            FROM fina_db.default_table
            GROUP BY ts_code, end_date
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    publish_multi = con.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT ts_code, end_date, COUNT(DISTINCT f_ann_date) AS cnt
            FROM (
                SELECT ts_code, end_date, f_ann_date FROM income_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM balance_db.default_table WHERE f_ann_date IS NOT NULL
                UNION ALL
                SELECT ts_code, end_date, f_ann_date FROM cashflow_db.default_table WHERE f_ann_date IS NOT NULL
            )
            GROUP BY ts_code, end_date
            HAVING COUNT(DISTINCT f_ann_date) > 1
        )
        """
    ).fetchone()[0]
    asof_dup = con.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT signal_date, symbol, COUNT(*) AS cnt
            FROM financial_quality_asof
            GROUP BY signal_date, symbol
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    return {
        "fina_duplicate_keys": int(fina_dup),
        "publish_keys_with_multiple_f_ann_date": int(publish_multi),
        "financial_asof_duplicate_keys": int(asof_dup),
    }


def distribution_table(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """输出因子分布诊断。"""
    rows = []
    for column in columns:
        series = pd.to_numeric(frame[column], errors="coerce").dropna()
        rows.append(
            {
                "字段": column,
                "样本数": len(series),
                "最小": series.min(),
                "P1": series.quantile(0.01),
                "P5": series.quantile(0.05),
                "中位数": series.median(),
                "P95": series.quantile(0.95),
                "P99": series.quantile(0.99),
                "最大": series.max(),
            }
        )
    return pd.DataFrame(rows)


def calculate_target_weight_stats(holdings: pd.DataFrame) -> pd.DataFrame:
    """按信号日收盘价近似计算 100 股取整后的目标权重分布。"""
    rows = []
    for signal_date, group in holdings.groupby("signal_date", sort=True):
        notional = (group["close"] * ((1_000_000 * 0.05 / group["close"]) // 100 * 100)).astype(float)
        weights = notional / notional.sum()
        rows.append(
            {
                "signal_date": signal_date,
                "持仓数": len(group),
                "最小权重": weights.min(),
                "中位权重": weights.median(),
                "最大权重": weights.max(),
                "单期权重离散度": weights.std(ddof=0),
            }
        )
    return pd.DataFrame(rows)


def estimate_holding_contributions(
    holdings: pd.DataFrame,
    selections: dict[str, list[str]],
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> pd.DataFrame:
    """估算每个信号持有期的单票等权贡献。"""
    dates = sorted(pd.Timestamp(date) for date in selections)
    rows = []
    holding_lookup = holdings.set_index(["signal_date", "symbol"])
    for index, signal_date in enumerate(dates):
        next_dates = [date for date in calendar if date > signal_date]
        if not next_dates:
            continue
        entry_date = next_dates[0]
        if index + 1 < len(dates):
            exit_candidates = [date for date in calendar if date > dates[index + 1]]
            exit_date = exit_candidates[0] if exit_candidates else calendar[-1]
        else:
            exit_date = calendar[-1]
        for symbol in selections[signal_date.strftime("%Y%m%d")]:
            try:
                entry_bar = bars.loc[(entry_date, symbol)]
                exit_bar = bars.loc[(exit_date, symbol)]
                entry_price = float(entry_bar["open"])
                exit_price = float(exit_bar["open"])
                period_return = exit_price / entry_price - 1
                meta = holding_lookup.loc[(signal_date.strftime("%Y%m%d"), symbol)]
            except KeyError:
                continue
            rows.append(
                {
                    "signal_date": signal_date.strftime("%Y%m%d"),
                    "entry_date": entry_date.strftime("%Y%m%d"),
                    "exit_date": exit_date.strftime("%Y%m%d"),
                    "symbol": symbol,
                    "name": meta.get("name", ""),
                    "period_return": period_return,
                    "equal_weight_contribution": period_return / 20,
                }
            )
    return pd.DataFrame(rows)


def find_max_drawdown_period(values: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    """定位最大回撤起点和谷底。"""
    running_max = values.expanding().max()
    drawdown = values / running_max - 1
    trough = drawdown.idxmin()
    peak = values.loc[:trough].idxmax()
    return peak, trough, float(drawdown.loc[trough])


def fmt_float_table(frame: pd.DataFrame, percent_columns: list[str] | None = None) -> pd.DataFrame:
    """格式化表格，便于写入 Markdown。"""
    formatted = frame.copy()
    percent_columns = percent_columns or []
    for column in formatted.columns:
        if column in percent_columns:
            formatted[column] = formatted[column].map(lambda value: f"{value:.2%}")
        elif pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda value: f"{value:.2f}")
    return formatted


def render_report(sections: dict[str, pd.DataFrame], summary: dict[str, object]) -> str:
    """渲染审计报告。"""
    return f"""# Quality Strategy V1 审计报告

## 审计结论

- 是否存在未来函数：{summary["future_status"]}
- 是否存在 ST / 退市 / 低成交额进入 Top20：{summary["tradability_status"]}
- 名称含 ST/退记录数：{summary["name_risk_records"]}
- 当前已退市或有退市日期记录数：{summary["eventually_delisted_records"]}
- 上市不足 3 年 Top20 记录数：{summary["young_records"]}
- 本地行业树未知覆盖率：{summary["unknown_industry_ratio"]}
- fina_indicator 重复键数：{summary["fina_duplicate_keys"]}
- f_ann_date 多来源不一致键数：{summary["publish_keys_with_multiple_f_ann_date"]}
- as-of 快照重复键数：{summary["financial_asof_duplicate_keys"]}
- 最大回撤区间：{summary["drawdown_period"]}
- 完整月度 Top20 持仓：`{HOLDINGS_PATH}`
- 最差贡献明细：`{WORST_PATH}`

## 最常出现的前 50 只持仓

{markdown_table(sections["top50"])}

## 最差贡献前 20 只持仓

{markdown_table(sections["worst20"])}

## 最大回撤期间高频持仓

{markdown_table(sections["drawdown_holdings"])}

## 持仓市值分布

{markdown_table(sections["weight_stats"])}

## 行业分布

{markdown_table(sections["industry"])}

## 可用财务数据股票数量

{markdown_table(sections["available_counts"])}

## 因子原始值分布

{markdown_table(sections["raw_distribution"])}

## Winsorize 后分布

{markdown_table(sections["winsorized_distribution"])}

## Top20 极端值诊断

{markdown_table(sections["extreme_top20"])}

## 报告期混用诊断

{markdown_table(sections["report_period"])}

## 低基数高增长诊断

{markdown_table(sections["high_growth"])}

## 策略定义有效性判断

当前 Quality V1 的 as-of 约束基本成立，但策略定义不够干净：

1. `fina_indicator` 没有原生 `f_ann_date`，当前通过三张原始财报表按 `ts_code + end_date`
   聚合出 `MAX(f_ann_date)` 再关联，虽然避免了未来函数，但存在披露日期多来源不一致风险。
2. 选股混用了 03/31、06/30、09/30、12/31 报告期，无法确认 `roe/roa/ocf_to_or`
   是季度、年度还是 TTM 同一口径。
3. Top20 中有不少财务极端值被缩尾后仍进入组合，说明当前定义更像“极端盈利能力排序”，
   不是稳健质量组合。
4. 行业覆盖在本地行业树上不完整，因此当前行业集中风险只能部分审计。

结论：当前 Quality V1 可作为 as-of 技术验证，但不建议认定为有效的实盘质量策略定义。
"""


def main() -> None:
    """执行审计并输出报告。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_financial_asof_table(con)
        candidates = load_audit_candidates(con)
        scored, holdings = build_scored_holdings(candidates)
        holdings = add_industry(add_audit_flags(holdings))
        selections, _ = build_quality_selections(candidates)
        symbols = sorted(holdings["symbol"].unique().tolist())
        bars = load_research_bars(con, symbols)
        calendar = load_calendar(con)
        result = run_monthly_backtest("Quality Strategy V1", selections, bars, calendar, ExecutionModel(slippage_bps=5.0))
        contribution = estimate_holding_contributions(holdings, selections, bars, calendar)
        contribution.to_csv(WORST_PATH, index=False, encoding="utf-8-sig")
        holdings.to_csv(HOLDINGS_PATH, index=False, encoding="utf-8-sig")

        join_diag = diagnose_financial_join(con)
        peak, trough, drawdown = find_max_drawdown_period(result.daily_values)
        dd_holdings = holdings[
            (pd.to_datetime(holdings["signal_date"], format="%Y%m%d") >= peak)
            & (pd.to_datetime(holdings["signal_date"], format="%Y%m%d") <= trough)
        ]
        raw_dist = distribution_table(scored, QUALITY_COLUMNS)
        winsorized_cols = []
        for column in QUALITY_COLUMNS:
            scored[f"{column}_winsorized"] = winsorize_series(scored[column])
            winsorized_cols.append(f"{column}_winsorized")
        winsorized_dist = distribution_table(scored, winsorized_cols)
        top50 = holdings.groupby(["symbol", "name"], dropna=False).agg(
            出现次数=("signal_date", "count"),
            平均排名=("rank", "mean"),
            平均分数=("quality_score", "mean"),
            平均ROE=("roe", "mean"),
            平均ROA=("roa", "mean"),
            平均OCF_to_OR=("ocf_to_or", "mean"),
        ).reset_index().sort_values(["出现次数", "平均分数"], ascending=[False, False]).head(50)
        worst20 = contribution.sort_values("equal_weight_contribution").head(20)
        industry = holdings.groupby("industry_level1").size().reset_index(name="持仓记录数")
        industry["占比"] = industry["持仓记录数"] / len(holdings)
        available = scored.groupby("signal_date").agg(
            可评分股票数=("symbol", "count"),
            Top20数量=("rank", lambda value: int((value <= 20).sum())),
        ).reset_index()
        weight_stats = calculate_target_weight_stats(holdings).describe().loc[["mean", "min", "max"]].reset_index()
        extreme_top20 = pd.DataFrame(
            [
                {"项目": "ROE被缩尾仍入选", "记录数": int(holdings["roe_clipped"].sum())},
                {"项目": "ROA被缩尾仍入选", "记录数": int(holdings["roa_clipped"].sum())},
                {"项目": "ocf_to_or被缩尾仍入选", "记录数": int(holdings["ocf_to_or_clipped"].sum())},
                {"项目": "ROE > 100", "记录数": int((holdings["roe"] > 100).sum())},
                {"项目": "ROA > 50", "记录数": int((holdings["roa"] > 50).sum())},
                {"项目": "ocf_to_or > 100", "记录数": int((holdings["ocf_to_or"] > 100).sum())},
            ]
        )
        report_period = holdings.groupby("report_period").size().reset_index(name="Top20记录数")
        high_growth = pd.DataFrame(
            [
                {"项目": "营收增长率 > 100%", "记录数": int((holdings["tr_yoy"] > 100).sum())},
                {"项目": "营收增长率 > 300%", "记录数": int((holdings["tr_yoy"] > 300).sum())},
                {"项目": "营收增长率 < -30%", "记录数": int((holdings["tr_yoy"] < -30).sum())},
                {"项目": "Top20营收增长率中位数", "记录数": float(holdings["tr_yoy"].median())},
            ]
        )
        sections = {
            "top50": fmt_float_table(top50),
            "worst20": fmt_float_table(
                worst20[["signal_date", "entry_date", "exit_date", "symbol", "name", "period_return", "equal_weight_contribution"]],
                ["period_return", "equal_weight_contribution"],
            ),
            "drawdown_holdings": fmt_float_table(
                dd_holdings.groupby(["symbol", "name"], dropna=False).size().reset_index(name="回撤期出现次数")
                .sort_values("回撤期出现次数", ascending=False).head(30)
            ),
            "weight_stats": fmt_float_table(weight_stats, ["最小权重", "中位权重", "最大权重", "单期权重离散度"]),
            "industry": fmt_float_table(industry.sort_values("持仓记录数", ascending=False), ["占比"]),
            "available_counts": fmt_float_table(available.describe().loc[["mean", "min", "max"]].reset_index()),
            "raw_distribution": fmt_float_table(raw_dist),
            "winsorized_distribution": fmt_float_table(winsorized_dist),
            "extreme_top20": fmt_float_table(extreme_top20),
            "report_period": fmt_float_table(report_period.sort_values("report_period")),
            "high_growth": fmt_float_table(high_growth),
        }
        summary = {
            **join_diag,
            "future_status": "FAIL" if holdings["future_function_violation"].any() else "PASS",
            "tradability_status": "FAIL"
            if (
                holdings["is_st"].any()
                or holdings["is_delisted_on_signal"].any()
                or holdings["low_amount"].any()
                or holdings["name_contains_st_or_delist"].any()
                or holdings["eventually_delisted"].any()
            )
            else "PASS",
            "name_risk_records": int(holdings["name_contains_st_or_delist"].sum()),
            "eventually_delisted_records": int(holdings["eventually_delisted"].sum()),
            "young_records": int(holdings["listed_lt_3y"].sum()),
            "unknown_industry_ratio": f"{(holdings['industry_level1'] == '未知').mean():.2%}",
            "drawdown_period": f"{peak:%Y-%m-%d} 至 {trough:%Y-%m-%d}，{drawdown:.2%}",
        }
        REPORT_PATH.write_text(render_report(sections, summary), encoding="utf-8")
        print(f"审计报告已写入: {REPORT_PATH}")
        print(f"完整持仓已写入: {HOLDINGS_PATH}")
        print(f"最差贡献已写入: {WORST_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
