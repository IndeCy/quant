"""Quality 防御与主线链动组合报告渲染。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: pd.DataFrame,
    correlations: dict[str, float],
    drawdown: dict[str, Any],
    gate: dict[str, Any],
    audit: dict[str, Any],
    allocation_cost: float,
) -> str:
    """输出袖套比较、分散贡献和固定门槛。"""
    period_rows: list[str] = []
    for period, sleeves in metrics.items():
        for sleeve, item in sleeves.items():
            period_rows.append(
                f"| {period} | {sleeve} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    annual_rows = "\n".join(
        f"| {row.year} | {row.combined_return:.2%} | {row.core_return:.2%} | "
        f"{row.satellite_return:.2%} | {row.combined_max_drawdown:.2%} |"
        for row in annual.itertuples(index=False)
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    correlation_rows = "\n".join(
        f"| {period} | {value:.3f} |"
        for period, value in correlations.items()
    )
    decision = (
        "进入组合级前向 Paper，不直接替代两个底层策略"
        if gate["passed"]
        else (
            "全样本风险收益有改善，但未通过全部冻结门槛；"
            "不进入组合级 Paper，保持两个底层策略独立观察"
        )
    )
    return f"""# Quality 防御核心 × 主线链动 70/30 V1

- 严格共同区间：{audit['start_date']} 至 {audit['end_date']}，
  {audit['common_days']} 个交易日。
- Core 70%：Quality 防守资产 V2；Satellite 30%：主线链动 V1。
- 每月末信号、下一交易日恢复 70/30，月内允许权重漂移。
- 组合级额外调拨成本：{allocation_cost:.6f} 净值单位。

| 阶段 | 袖套 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额 | 调拨换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

## 年度表现

| 年份 | 组合 | Core | Satellite | 组合最大回撤 |
|---|---:|---:|---:|---:|
{annual_rows}

## 袖套相关性

| 阶段 | 日收益相关性 |
|---|---:|
{correlation_rows}

## 最大回撤归因

- 区间：{drawdown['peak_date']} 至 {drawdown['trough_date']}。
- 组合：{drawdown['combined_return']:.2%}。
- Core：{drawdown['core_return']:.2%}。
- Satellite：{drawdown['satellite_return']:.2%}。
- 510300：{drawdown['benchmark_return']:.2%}。

## 固定门槛

{checks}

## 结论

{decision}。
"""
