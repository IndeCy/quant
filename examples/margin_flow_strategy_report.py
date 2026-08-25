"""融资净买入强度策略报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    candidate_counts: dict[str, float],
    diagnostics: dict[str, float],
    quality_correlation: float,
    latest_date: str,
) -> str:
    """输出分阶段指标、动量归因和固定门槛。"""
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
    return f"""# 融资净买入强度 V1

- 截止：{latest_date}。
- 因子：T-1 截止的 20 日融资净买入额 / 同期成交额，正值 Top20。
- 正候选中位数：{candidate_counts['median']:.0f}，最新：
  {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与 20/120 日动量截面 Spearman 中位数：
  {diagnostics['median_spearman_ret20']:.3f} /
  {diagnostics['median_spearman_ret120']:.3f}。
- 与 120 日动量 Top20 持仓重叠中位数：
  {diagnostics['median_top20_overlap_with_momentum']:.1%}。

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
