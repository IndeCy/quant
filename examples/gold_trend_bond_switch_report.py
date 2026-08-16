"""黄金趋势与国债切换策略研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染多折、年度、状态归因和固定门槛。"""
    periods = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
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
        f"{item['cumulative_return']:.2%} | {item['annualized_return']:.2%} | "
        f"{item['positive_day_ratio']:.1%} |"
        for name, item in result["state_attribution"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    latest = result["latest_state"]
    return f"""# 黄金趋势国债切换 V1

- 数据共同截止：{result['latest_date']}。
- 月末黄金 MA60 > MA120 时持有黄金，否则持有5年国债。
- 信号在月末收盘形成，下一交易日经 M0 成交。
- 统一qfq、5bps、ETF免印花税，不叠加额外风险层。
- 与 Quality 日收益相关性：{result['quality_return_correlation']:.3f}。
- 最新状态：{'黄金趋势' if latest['trend_active'] else '国债防守'}，
  MA60={latest['ma60']:.3f}，MA120={latest['ma120']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{periods}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
{comparisons}

## 状态归因

| 状态 | 交易日 | 时间占比 | 累计收益 | 状态年化 | 日胜率 |
|---|---:|---:|---:|---:|---:|
{states}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 固定门槛

{checks}

结论：{'通过固定多折门槛，仅允许进入前瞻Paper确认' if result['gate']['passed'] else '未通过固定门槛，终止该路线'}。
"""
