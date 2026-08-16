"""Piotroski 价值研究报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    coverage: dict[str, Any],
    quality_correlation: float,
    latest_date: str,
) -> str:
    """输出固定定义、分阶段指标和明确决策。"""
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for name, item in metrics.items()
    )
    years = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} |"
        for year, item in annual.items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    decision = (
        "进入独立前向 Paper 观察，不直接注册生产"
        if gate["passed"]
        else "终止并归档，不注册生产策略"
    )
    return f"""# Piotroski 价值策略 V1

- 截止：{latest_date}。
- 价值池：账面市值比最高 20%，F-Score >= 8，最多 Top20 月频等权。
- 月度候选中位数：{coverage['median_candidates']:.0f}，最新：
  {coverage['latest_candidates']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。

| 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年换手 |
|---|---:|---:|---:|---:|---:|---:|
{periods}

## 年度表现

| 年份 | 收益 | 最大回撤 |
|---|---:|---:|
{years}

## 固定门槛

{checks}

## 结论

{decision}。
"""
