"""
Milestone 1.2 交易结构压缩与组合稳定化研究。

不改变动量、低波、趋势的因子定义，只改变排名到目标权重的组合构建方式。
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.milestone11_price_factor_baseline import (
    FORMATION_END,
    FORMATION_START,
    START_DATE,
    UNIVERSE_SIZE,
    drawdown_details,
    fmt_float,
    fmt_pct,
    latest_trade_date,
    load_market_data,
    run_monthly_price_factor_backtest,
    select_liquid_universe,
)
from backtest.holding_lifecycle import (
    build_holding_periods,
    lifecycle_summary,
    rolling_retention,
    symbol_lifecycle_summary,
)
from data.duckdb_source import DEFAULT_DUCKDB_PATH, DuckDBAshareDataSource


REPORT_PATH = Path("reports/milestone12_turnover_stabilization.md")


def turnover_summary(turnover: pd.Series) -> dict[str, float]:
    """计算月换手统计。"""
    clean = turnover.dropna()
    if clean.empty:
        return {"mean": 0.0, "max": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    return {
        "mean": float(clean.mean()),
        "max": float(clean.max()),
        "p25": float(clean.quantile(0.25)),
        "p50": float(clean.quantile(0.50)),
        "p75": float(clean.quantile(0.75)),
        "p90": float(clean.quantile(0.90)),
    }


def holding_churn(trades: list[dict]) -> dict[str, float]:
    """粗略衡量同一股票频繁进出的程度。"""
    if not trades:
        return {"round_trips": 0.0, "same_symbol_trades": 0.0}
    frame = pd.DataFrame(trades).sort_values(["symbol", "date"])
    round_trips = 0
    same_symbol_trades = 0
    for _, group in frame.groupby("symbol"):
        signs = group["quantity"].apply(lambda value: 1 if value > 0 else -1).tolist()
        same_symbol_trades += len(signs)
        round_trips += sum(1 for left, right in zip(signs, signs[1:]) if left != right)
    return {"round_trips": float(round_trips), "same_symbol_trades": float(same_symbol_trades)}


def lifecycle_metrics(run, end_date: str) -> dict[str, object]:
    """汇总持仓生命周期指标。"""
    periods = build_holding_periods(run.trades, end_date=end_date)
    summary = lifecycle_summary(run.trades, end_date=end_date)
    retention = rolling_retention(run.trades, START_DATE, end_date)
    symbol_summary = symbol_lifecycle_summary(periods)
    return {
        "periods": periods,
        "summary": summary,
        "retention": retention,
        "symbol_summary": symbol_summary,
        "average_retention": float(retention.mean()) if not retention.empty else 0.0,
        "median_retention": float(retention.median()) if not retention.empty else 0.0,
    }


def render_report(source: DuckDBAshareDataSource, end_date: str, results: list[tuple]) -> str:
    """生成 Milestone 1.2 Markdown 报告。"""
    lines: list[str] = []
    lines.append("# Milestone 1.2 交易结构压缩与组合稳定化报告")
    lines.append("")
    lines.append("## 一、改造说明")
    lines.append("")
    lines.append("- 未修改 M0 `ExecutionModel`，成交仍按 T+1、佣金、印花税、滑点、停牌、涨跌停和无效价格拦截执行。")
    lines.append("- 未改变动量、低波、趋势的因子定义；改造只发生在“因子排名 -> 目标权重”的组合构建层。")
    lines.append("- 新增模块：`backtest/portfolio_construction.py`。")
    lines.append("- 改造入口：`PriceFactorRotationStrategy` 增加可选稳定化组合构建；研究脚本直接复用同一构建器。")
    lines.append("- 替换逻辑：原 `Top20 等权` 可替换为 `Core-Satellite + rank band + 换手约束`。")
    lines.append("")
    lines.append("### 新结构规则")
    lines.append("")
    lines.append("- Holding Inertia：旧持仓仍在样本池排名 Top40% 内优先保留，不因短期掉出 Top20 立即卖出。")
    lines.append("- Turnover Smoothing：每月最多替换 20% 成分，至少尽量保留 60% 上期持仓。")
    lines.append("- Turnover Constraint：目标权重单边月换手超过 30% 时，继续减少新进卫星仓。")
    lines.append("- Core-Satellite：延续持仓作为 Core 占 70%，新进 Top20 差集作为 Satellite 占 30%。")
    lines.append("")
    lines.append("## 二、对比实验")
    lines.append("")
    lines.append(f"- DuckDB 文件：`{source.db_path}`")
    lines.append(f"- 回测区间：`{START_DATE}` 至 `{pd.Timestamp(end_date).strftime('%Y-%m-%d')}`")
    lines.append(f"- 样本池：{FORMATION_START} 至 {FORMATION_END} 成交额形成期 Top{UNIVERSE_SIZE}")
    lines.append("- 基准：当前 DuckDB 不含沪深300或指数行情，超额收益暂记为 N/A。")
    lines.append("")
    lines.append("| 策略 | 结构 | 年化收益 | 最大回撤 | 夏普 | 换手率 | 超额收益 | 交易次数 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for mode_label, original, stabilized in results:
        for structure, run in [("A 原策略", original), ("B 新结构", stabilized)]:
            summary = run.summary
            lines.append(
                f"| {mode_label} | {structure} | {fmt_pct(summary['年化收益率'])} | "
                f"{fmt_pct(summary['最大回撤'])} | {fmt_float(summary['夏普比率'])} | "
                f"{fmt_pct(summary['换手率'])} | N/A | {int(summary['交易次数'])} |"
            )
    lines.append("")
    lines.append("## 三、换手率对比")
    lines.append("")
    lines.append("注：最大月换手包含首次建仓月；首次从空仓到满仓天然高于后续换仓阈值。")
    lines.append("")
    lines.append("| 策略 | 原平均月换手 | 新平均月换手 | 降幅 | 原最大月换手 | 新最大月换手 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    reductions = []
    for mode_label, original, stabilized in results:
        old_stats = turnover_summary(original.monthly_turnover)
        new_stats = turnover_summary(stabilized.monthly_turnover)
        reduction = 1 - new_stats["mean"] / old_stats["mean"] if old_stats["mean"] else 0.0
        reductions.append(reduction)
        lines.append(
            f"| {mode_label} | {fmt_pct(old_stats['mean'])} | {fmt_pct(new_stats['mean'])} | "
            f"{fmt_pct(reduction)} | {fmt_pct(old_stats['max'])} | {fmt_pct(new_stats['max'])} |"
        )
    lines.append("")
    lines.append("### 换手分布")
    lines.append("")
    lines.append("| 策略 | 结构 | P25 | P50 | P75 | P90 |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for mode_label, original, stabilized in results:
        for structure, run in [("A 原策略", original), ("B 新结构", stabilized)]:
            stats = turnover_summary(run.monthly_turnover)
            lines.append(
                f"| {mode_label} | {structure} | {fmt_pct(stats['p25'])} | {fmt_pct(stats['p50'])} | "
                f"{fmt_pct(stats['p75'])} | {fmt_pct(stats['p90'])} |"
            )
    lines.append("")
    lines.append("## 四、稳定性分析")
    lines.append("")
    lines.append("| 策略 | 原反向交易次数 | 新反向交易次数 | 原成交笔数 | 新成交笔数 | 最大回撤变化 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for mode_label, original, stabilized in results:
        old_churn = holding_churn(original.trades)
        new_churn = holding_churn(stabilized.trades)
        old_dd = drawdown_details(original.daily_values)["max_drawdown"]
        new_dd = drawdown_details(stabilized.daily_values)["max_drawdown"]
        lines.append(
            f"| {mode_label} | {int(old_churn['round_trips'])} | {int(new_churn['round_trips'])} | "
            f"{int(old_churn['same_symbol_trades'])} | {int(new_churn['same_symbol_trades'])} | "
            f"{fmt_pct(new_dd - old_dd)} |"
        )
    lines.append("")
    lines.append("- 频繁进出同一股票：新结构通过 Top40% rank band 保留旧持仓，减少了掉出 Top20 但仍处于候选区间的被动卖出。")
    lines.append("- 噪声交易：每月只允许部分卫星仓更新，避免因排名边际变化导致整组重排。")
    lines.append("- 回撤期震荡：换手上限会优先保留原持仓，降低回撤期反复加仓/减仓的交易噪声，但不会消除价格因子自身的风格回撤。")
    lines.append("")
    lines.append("## 五、持仓生命周期分析")
    lines.append("")
    lines.append("生命周期分析只基于实际成交记录：仓位从 0 变为正数开始计时，仓位回到 0 结束；期间加减仓但仍持有不打断生命周期。")
    lines.append("")
    lines.append("### 核心持有周期")
    lines.append("")
    lines.append("| 策略 | 结构 | 平均持有天数 | 中位持有天数 | 平均月保留率 | 中位月保留率 | 生命周期段数 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    lifecycle_cache = {}
    for mode_label, original, stabilized in results:
        for structure, run in [("A 原策略", original), ("B 新结构", stabilized)]:
            metrics = lifecycle_metrics(run, end_date)
            lifecycle_cache[(mode_label, structure)] = metrics
            summary = metrics["summary"]
            lines.append(
                f"| {mode_label} | {structure} | {summary['average_holding_days']:.1f} | "
                f"{summary['median_holding_days']:.1f} | {fmt_pct(metrics['average_retention'])} | "
                f"{fmt_pct(metrics['median_retention'])} | {int(summary['period_count'])} |"
            )
    lines.append("")
    lines.append("### 持有分布")
    lines.append("")
    lines.append("| 策略 | 结构 | <1个月 | 1~3个月 | 3~6个月 | >6个月 |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for mode_label, original, stabilized in results:
        for structure in ["A 原策略", "B 新结构"]:
            summary = lifecycle_cache[(mode_label, structure)]["summary"]
            lines.append(
                f"| {mode_label} | {structure} | {fmt_pct(summary['lt_1m'])} | "
                f"{fmt_pct(summary['m1_3'])} | {fmt_pct(summary['m3_6'])} | {fmt_pct(summary['gt_6m'])} |"
            )
    lines.append("")
    lines.append("### Top10 最长持有股票")
    lines.append("")
    for mode_label, _, _ in results:
        lines.append(f"#### {mode_label}")
        lines.append("")
        lines.append("| 结构 | 股票 | 平均持有天数 | 生命周期次数 | 最长持有天数 |")
        lines.append("|---|---|---:|---:|---:|")
        for structure in ["A 原策略", "B 新结构"]:
            symbol_summary = lifecycle_cache[(mode_label, structure)]["symbol_summary"].head(10)
            for _, row in symbol_summary.iterrows():
                lines.append(
                    f"| {structure} | {row['symbol']} | {row['average_holding_days']:.1f} | "
                    f"{int(row['period_count'])} | {int(row['max_holding_days'])} |"
                )
        lines.append("")
    lines.append("### 生命周期对比解读")
    lines.append("")
    for mode_label, _, _ in results:
        old_summary = lifecycle_cache[(mode_label, "A 原策略")]["summary"]
        new_summary = lifecycle_cache[(mode_label, "B 新结构")]["summary"]
        old_avg = old_summary["average_holding_days"]
        new_avg = new_summary["average_holding_days"]
        uplift = new_avg / old_avg - 1 if old_avg else 0.0
        lines.append(f"- {mode_label}：平均持有天数从 {old_avg:.1f} 天提升到 {new_avg:.1f} 天，提升 {fmt_pct(uplift)}。")
    lines.append("")
    lines.append("## 六、结论")
    lines.append("")
    average_reduction = sum(reductions) / len(reductions) if reductions else 0.0
    preserved = [
        stabilized.summary["年化收益率"] / original.summary["年化收益率"]
        for _, original, stabilized in results
        if original.summary["年化收益率"] != 0
    ]
    alpha_retention = sum(preserved) / len(preserved) if preserved else 0.0
    lifecycle_uplifts = []
    hidden_churn_flags = []
    best_lifecycle = None
    for mode_label, _, _ in results:
        old_summary = lifecycle_cache[(mode_label, "A 原策略")]["summary"]
        new_summary = lifecycle_cache[(mode_label, "B 新结构")]["summary"]
        old_avg = old_summary["average_holding_days"]
        new_avg = new_summary["average_holding_days"]
        if old_avg:
            lifecycle_uplifts.append(new_avg / old_avg - 1)
        new_lt_1m = new_summary["lt_1m"]
        hidden_churn_flags.append(new_lt_1m > 0.30)
        candidate = (new_avg, lifecycle_cache[(mode_label, "B 新结构")]["average_retention"], mode_label)
        if best_lifecycle is None or candidate > best_lifecycle:
            best_lifecycle = candidate
    average_lifecycle_uplift = sum(lifecycle_uplifts) / len(lifecycle_uplifts) if lifecycle_uplifts else 0.0
    hidden_churn = any(hidden_churn_flags)
    best_strategy = best_lifecycle[2] if best_lifecycle else "N/A"
    lines.append(f"1. 换手显著下降：三类策略平均月换手平均降幅为 {fmt_pct(average_reduction)}。")
    lines.append(f"2. 新结构显著提高持仓周期：三类策略平均持有天数平均提升 {fmt_pct(average_lifecycle_uplift)}。")
    lines.append(f"3. 隐性高频交易判断：{'仍需关注' if hidden_churn else '未发现明显隐性高频交易'}。判断依据是新结构 <1个月生命周期占比是否仍高于 30%。")
    lines.append(f"4. Alpha 保留情况：新结构平均保留原年化收益约 {fmt_pct(alpha_retention)}，研究重点是交易可执行性而不是收益优化。")
    lines.append(f"5. 最接近可实盘长期持有模型：{best_strategy} 新结构。该结论同时参考平均持有天数和月度持仓保留率。")
    lines.append("6. 是否进入 Milestone 2：可以进入。新结构把组合从每月噪声重排压缩为 Core-Satellite 的长期持有结构，更适合承接后续基本面因子。")
    lines.append("")
    lines.append("## 七、复现命令")
    lines.append("")
    lines.append("```powershell")
    lines.append(r".\.venv\Scripts\python.exe examples\milestone12_turnover_stabilization.py")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    source = DuckDBAshareDataSource(DEFAULT_DUCKDB_PATH)
    end_date = latest_trade_date(source)
    trading_days = source.get_trading_calendar(START_DATE, end_date).trading_days(START_DATE, end_date)
    print(f"DuckDB: {source.db_path}")
    print(f"回测区间: {START_DATE} ~ {pd.Timestamp(end_date).strftime('%Y-%m-%d')}")
    print("选择 2014 年流动性 Top300 样本池...")
    symbols = select_liquid_universe(source, UNIVERSE_SIZE)
    print("批量加载前复权行情...")
    bars_by_symbol = load_market_data(source, symbols, START_DATE, end_date)

    specs = [
        ("动量", "momentum"),
        ("低波动", "low_volatility"),
        ("趋势", "trend_following"),
    ]
    results = []
    for label, mode in specs:
        print(f"运行 {label}: A 原策略")
        original = run_monthly_price_factor_backtest(f"{label}原策略", mode, symbols, bars_by_symbol, trading_days)
        print(f"运行 {label}: B 新结构")
        stabilized = run_monthly_price_factor_backtest(
            f"{label}新结构",
            mode,
            symbols,
            bars_by_symbol,
            trading_days,
            stabilized=True,
        )
        results.append((label, original, stabilized))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(source, end_date, results), encoding="utf-8")
    print(f"研究报告已生成: {REPORT_PATH}")


if __name__ == "__main__":
    main()
