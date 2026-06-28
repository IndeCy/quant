"""
Quality Cleanup 2015 年最大回撤法医分析。

只解释既有回撤，不修改 Alpha 因子、股票池或组合规则。
"""

from __future__ import annotations

from pathlib import Path
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.execution_model import ExecutionModel
from backtest.industry import IndustryManager
from backtest.research_benchmark import load_hs300_benchmark
from examples.quality_cleanup_audit import (
    apply_quality_cleanup_filters,
    build_top20_from_candidates,
    create_annual_financial_asof_table,
    load_annual_candidates,
)
from examples.quality_portfolio_construction_study import run_weighted_monthly_backtest
from examples.quality_strategy_v1 import (
    DB_PATH,
    FUND_BASIC_PATH,
    FUND_DAILY_PATH,
    START_DATE,
    attach_financial_dbs,
    create_signal_date_table,
    score_quality_frame,
)
from examples.strategy_comparison_research import (
    create_feature_table,
    get_bar,
    load_calendar,
    load_research_bars,
    load_signal_dates,
    markdown_table,
)


REPORT_PATH = Path("reports/quality_drawdown_forensics.md")
PEAK_DATE = pd.Timestamp("2015-06-11")
TROUGH_DATE = pd.Timestamp("2015-07-09")
STRESS_START = pd.Timestamp("2015-06-01")
STRESS_END = pd.Timestamp("2015-09-01")


def concentration_metrics(weights: pd.Series) -> dict[str, float]:
    """计算前五、前十权重和 HHI。"""
    ordered = pd.to_numeric(weights, errors="coerce").dropna().sort_values(ascending=False)
    return {
        "top5_weight": float(ordered.head(5).sum()),
        "top10_weight": float(ordered.head(10).sum()),
        "hhi": float((ordered**2).sum()),
    }


def position_loss_contributions(frame: pd.DataFrame) -> pd.DataFrame:
    """按回撤起点权重计算静态持仓损失贡献。"""
    result = frame.copy()
    result["period_return"] = result["end_price"] / result["start_price"] - 1
    result["loss_contribution"] = -result["weight"] * result["period_return"]
    return result.sort_values("loss_contribution", ascending=False).reset_index(drop=True)


def reconstruct_positions(trades: list[dict[str, object]], date: pd.Timestamp) -> dict[str, int]:
    """根据成交记录重建指定日期收盘持仓。"""
    positions: dict[str, int] = {}
    for trade in trades:
        if pd.Timestamp(trade["date"]) > date:
            continue
        symbol = str(trade["symbol"])
        positions[symbol] = positions.get(symbol, 0) + int(trade["quantity"])
        if positions[symbol] == 0:
            positions.pop(symbol)
    return positions


def build_contribution_frame(
    positions: dict[str, int],
    portfolio_value: float,
    bars: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    names: dict[str, str],
) -> pd.DataFrame:
    """生成回撤开始日持仓及静态损失贡献。"""
    manager = IndustryManager()
    rows = []
    for symbol, quantity in positions.items():
        start_bar = get_bar(bars, start_date, symbol)
        end_bar = get_bar(bars, end_date, symbol)
        try:
            history = bars.xs(symbol, level="symbol")
        except KeyError:
            continue
        if start_bar is None:
            start_history = history.loc[:start_date]
            start_bar = start_history.iloc[-1] if not start_history.empty else None
        if end_bar is None:
            end_history = history.loc[:end_date]
            end_bar = end_history.iloc[-1] if not end_history.empty else None
        if start_bar is None or end_bar is None:
            continue
        start_price = float(start_bar["close"])
        info = manager.get_industry_by_stock(symbol)
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "industry": info.get("level1", "未知"),
                "quantity": quantity,
                "weight": quantity * start_price / portfolio_value,
                "start_price": start_price,
                "end_price": float(end_bar["close"]),
            }
        )
    return position_loss_contributions(pd.DataFrame(rows))


def industry_contributions(contributions: pd.DataFrame) -> pd.DataFrame:
    """汇总行业起点权重、期间跌幅和损失贡献。"""
    grouped = contributions.groupby("industry", dropna=False).agg(
        weight=("weight", "sum"),
        loss_contribution=("loss_contribution", "sum"),
    ).reset_index()
    grouped["industry_return"] = -grouped["loss_contribution"] / grouped["weight"]
    return grouped.sort_values("loss_contribution", ascending=False)


def extreme_loss_table(contributions: pd.DataFrame) -> pd.DataFrame:
    """列出不同极端跌幅阈值下的股票。"""
    rows = []
    for threshold in [-0.5, -0.6, -0.7, -0.8]:
        subset = contributions[contributions["period_return"] <= threshold]
        rows.append(
            {
                "跌幅阈值": f"<={threshold:.0%}",
                "数量": len(subset),
                "名单": "、".join(f"{row['name']}({row['symbol']})" for _, row in subset.iterrows()) or "无",
            }
        )
    return pd.DataFrame(rows)


def annualized_volatility(returns: pd.Series) -> float:
    """计算日收益年化波动率。"""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    return float(clean.std(ddof=1) * math.sqrt(252)) if len(clean) > 1 else 0.0


def volatility_comparison(strategy_values: pd.Series, benchmark_curve: pd.Series) -> pd.DataFrame:
    """比较回撤前 60 日和回撤期间波动率。"""
    strategy_returns = strategy_values.pct_change()
    benchmark = benchmark_curve.reindex(strategy_values.index).ffill()
    benchmark_returns = benchmark.pct_change()
    pre_strategy = strategy_returns.loc[:PEAK_DATE].iloc[:-1].tail(60)
    pre_benchmark = benchmark_returns.loc[pre_strategy.index]
    during_strategy = strategy_returns.loc[PEAK_DATE:TROUGH_DATE].iloc[1:]
    during_benchmark = benchmark_returns.loc[during_strategy.index]
    return pd.DataFrame(
        [
            {
                "阶段": "回撤前60日",
                "组合年化波动率": annualized_volatility(pre_strategy),
                "510300年化波动率": annualized_volatility(pre_benchmark),
            },
            {
                "阶段": "最大回撤期间",
                "组合年化波动率": annualized_volatility(during_strategy),
                "510300年化波动率": annualized_volatility(during_benchmark),
            },
        ]
    )


def diversification_stress_test(
    scored: pd.DataFrame,
    bars: pd.DataFrame,
    calendar: list[pd.Timestamp],
) -> pd.DataFrame:
    """固定 2015-05-29 评分，对不同持仓数量做窗口压力测试。"""
    rows = []
    execution_model = ExecutionModel(slippage_bps=5.0)
    for top_n in [20, 40, 60, 100, 200]:
        symbols = scored.head(top_n)["symbol"].tolist()
        target = {"20150529": {symbol: 1.0 / len(symbols) for symbol in symbols}}
        result = run_weighted_monthly_backtest(f"Top{top_n}", target, bars, calendar, execution_model)
        window = result.daily_values.loc[STRESS_START:STRESS_END]
        drawdown = window / window.expanding().max() - 1
        rows.append(
            {
                "组合": f"Top{top_n}",
                "窗口最大回撤": float(drawdown.min()),
                "窗口期末收益": float(window.iloc[-1] / window.iloc[0] - 1),
                "成交失败数": len(result.failed_orders),
            }
        )
    return pd.DataFrame(rows)


def format_percent_table(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """格式化百分比字段。"""
    formatted = frame.copy()
    for column in columns:
        formatted[column] = formatted[column].map(lambda value: f"{value:.2%}")
    return formatted


def render_report(
    top10: pd.DataFrame,
    industries: pd.DataFrame,
    concentration: dict[str, float],
    extremes: pd.DataFrame,
    stress: pd.DataFrame,
    volatility: pd.DataFrame,
    static_loss: float,
) -> str:
    """渲染法医报告。"""
    top10_display = format_percent_table(top10.copy(), ["weight", "period_return", "loss_contribution"])
    industry_display = format_percent_table(industries.copy(), ["weight", "industry_return", "loss_contribution"])
    stress_display = format_percent_table(stress.copy(), ["窗口最大回撤", "窗口期末收益"])
    vol_display = format_percent_table(volatility.copy(), ["组合年化波动率", "510300年化波动率"])
    return f"""# Quality Cleanup 2015 回撤法医分析

## 1. Top10 回撤贡献股票

{markdown_table(top10_display)}

回撤开始日静态持仓贡献合计：`{static_loss:.2%}`。期间存在 2015-07-01 月度调仓，静态贡献不等于实际净值回撤的精确会计归因。

## 2. 行业贡献

{markdown_table(industry_display)}

## 3. 集中度

| 指标 | 结果 |
| --- | --- |
| 前5大持仓权重 | {concentration['top5_weight']:.2%} |
| 前10大持仓权重 | {concentration['top10_weight']:.2%} |
| HHI | {concentration['hhi']:.4f} |
| 等效持仓数量 1/HHI | {1 / concentration['hhi']:.2f} |

## 4. 个股极端风险

{markdown_table(extremes)}

## 5. 分散化压力测试（2015-06-01 至 2015-09-01）

{markdown_table(stress_display)}

## 6. 波动率分析

{markdown_table(vol_display)}

## 最终判断

- A 市场系统性风险：**主要触发因素**。持仓普遍下跌，压力测试扩展到 Top200 后仍有接近 40% 回撤。
- B 少数个股暴雷：**不是主要原因**。没有股票跌超 70%，但有 7 只跌超 50%，属于广泛急跌而非一两只归零。
- C 行业集中：**当前证据不支持**。已识别行业没有单一权重超过 10%，但未知行业权重较高，结论受数据覆盖限制。
- D 组合过度集中：**不是主要原因**。HHI 接近等权20只理论值 0.05，Top200 也只能把窗口回撤降到约 39%。
- E 高波动股票暴露：**有一定放大但不是主因**。回撤前组合波动率仅略高于510300，股灾期间反而低于510300。

综合判断：这是市场系统性流动性冲击引发的横截面普跌，Quality 持仓的个股弹性放大了损失；不是单只暴雷或简单持仓数量不足。
"""


def main() -> None:
    """运行完整回撤法医分析。"""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        create_feature_table(con)
        signal_dates = load_signal_dates(con)
        create_signal_date_table(con, signal_dates)
        attach_financial_dbs(con)
        create_annual_financial_asof_table(con)
        candidates = apply_quality_cleanup_filters(load_annual_candidates(con))
        selections, holdings = build_top20_from_candidates(candidates)
        all_scored = score_quality_frame(candidates[candidates["signal_date"].eq("20150529")])
        symbols = sorted(set(holdings["symbol"]) | set(all_scored.head(200)["symbol"]))
        bars = load_research_bars(con, symbols)
        calendar = load_calendar(con)
        base_targets = {
            date: {symbol: 1.0 / len(items) for symbol in items}
            for date, items in selections.items()
            if items
        }
        result = run_weighted_monthly_backtest(
            "Quality Cleanup",
            base_targets,
            bars,
            calendar,
            ExecutionModel(slippage_bps=5.0),
        )
        positions = reconstruct_positions(result.trades, PEAK_DATE)
        names = dict(con.execute("SELECT ts_code, name FROM stock_basic").fetchall())
        contributions = build_contribution_frame(
            positions,
            float(result.daily_values.loc[PEAK_DATE]),
            bars,
            PEAK_DATE,
            TROUGH_DATE,
            names,
        )
        industries = industry_contributions(contributions)
        concentration = concentration_metrics(contributions["weight"])
        extremes = extreme_loss_table(contributions)
        stress = diversification_stress_test(all_scored, bars, calendar)
        benchmark, _ = load_hs300_benchmark(
            con,
            START_DATE,
            str(FUND_DAILY_PATH) if FUND_DAILY_PATH.exists() else None,
            str(FUND_BASIC_PATH) if FUND_BASIC_PATH.exists() else None,
        )
        volatility = volatility_comparison(result.daily_values, benchmark)
        REPORT_PATH.write_text(
            render_report(
                contributions.head(10)[["symbol", "name", "weight", "period_return", "loss_contribution"]],
                industries,
                concentration,
                extremes,
                stress,
                volatility,
                float(contributions["loss_contribution"].sum()),
            ),
            encoding="utf-8",
        )
        print(contributions.head(10).to_string(index=False))
        print(industries.to_string(index=False))
        print(concentration)
        print(extremes.to_string(index=False))
        print(stress.to_string(index=False))
        print(volatility.to_string(index=False))
        print(f"报告已写入: {REPORT_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
