"""涨停首板封单强度次日轮换策略报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    periods = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['annual_turnover']:.1f}x |"
        for period, item in result["period_metrics"].items()
    )
    comparisons = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    conclusion = (
        "通过冻结门槛，仅允许继续研究，不进入生产"
        if result["gate"]["passed"]
        else "未通过冻结门槛，归档且不注册"
    )
    diagnostics = result["diagnostics"]
    return f"""# 涨停首板封单强度次日轮换 V1

- 研究区间：{result['period'][0]} 至 {result['period'][1]}。
- 每日收盘从非ST、非退市、open_times=0的涨停事件中，按封单额/成交额选前10名。
- T+1开盘经M0换入，持有一个交易日，于下一批目标执行时换出；无事件则现金。
- 基准执行：10bps滑点；压力执行：30bps；佣金、最低佣金、卖出印花税均启用。
- 对照：同日首板按成交额前10名，以及沪深300ETF买入持有。
- 与Quality日收益相关性：{diagnostics['quality_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{periods}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
{comparisons}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 执行与样本诊断

- 信号日：{diagnostics['signal_days']}，有候选日占比：{diagnostics['active_signal_share']:.2%}
- 唯一入选股票：{diagnostics['unique_selected_symbols']}
- 实际成交：{diagnostics['trade_count']}，失败委托：{diagnostics['failed_order_count']}
- 失败委托率：{diagnostics['failed_order_rate']:.2%}
- 年化波动：{diagnostics['annualized_volatility']:.2%}
- 最差单日：{diagnostics['worst_day']:.2%}
- 95% Expected Shortfall：{diagnostics['expected_shortfall_95']:.2%}
- 最长水下期：{diagnostics['max_underwater_days']}个交易日

## 冻结门槛

{checks}

结论：{conclusion}。
"""
