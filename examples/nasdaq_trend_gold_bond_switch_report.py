"""纳指趋势驱动黄金国债切换研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染候选、对照、年度、状态与冻结门槛。"""
    periods = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['annual_turnover']:.2f}x |"
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
    states = "\n".join(
        f"| {name} | {item['days']} | {item['day_share']:.1%} | "
        f"{item['annualized_return']:.2%} | {item['positive_day_ratio']:.1%} |"
        for name, item in result["state_attribution"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    latest = result["latest_state"]
    conclusion = (
        "通过冻结历史门槛，仅允许进入独立前向观察"
        if result["gate"]["passed"]
        else "未通过冻结门槛，归档且不注册"
    )
    return f"""# 纳指趋势驱动黄金国债切换 V1

- 数据共同截止：{result['latest_date']}。
- 月末纳指ETF MA20 > MA200 时持有纳指60%/黄金40%；
  否则切换为黄金50%/5年国债50%。
- 信号下一交易日经M0执行，统一qfq、5bps、ETF免印花税。
- 直接机会成本：静态纳指/黄金60/40与场内标普500ETF。
- 不做权重、窗口或调仓频率网格。
- 与Quality日收益相关性：{result['diagnostics']['quality_correlation']:.3f}。
- 最新状态：{'进攻' if latest['trend_active'] else '防守'}，
  MA20={latest['fast_ma']:.3f}，MA200={latest['slow_ma']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{periods}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
{comparisons}

## 状态归因

| 状态 | 交易日 | 时间占比 | 状态年化 | 日胜率 |
|---|---:|---:|---:|---:|
{states}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 尾部诊断

- 年化波动：{result['diagnostics']['annualized_volatility']:.2%}
- 最差单日：{result['diagnostics']['worst_day']:.2%}
- 95% Expected Shortfall：{result['diagnostics']['expected_shortfall_95']:.2%}
- 最长水下期：{result['diagnostics']['max_underwater_days']}个交易日

## 冻结门槛

{checks}

结论：{conclusion}。
"""
