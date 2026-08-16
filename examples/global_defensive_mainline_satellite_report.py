"""全球防守核心与 A 股主线卫星固定 80/20 研究报告。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    stress_metrics: dict[str, dict[str, dict[str, float]]],
    annual: pd.DataFrame,
    correlations: dict[str, float],
    tail: dict[str, float | int],
    gate: dict[str, Any],
    audit: dict[str, Any],
    *,
    allocation_cost: float,
    cost_drag: float,
    stress_cost_drag: float,
) -> str:
    """渲染固定定义、多折、压力和尾部风险证据。"""
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
    base = metrics["full"]["combined"]
    stress = stress_metrics["full"]["combined"]
    decision = (
        "通过冻结研究门槛；只允许进入组合级前向 Paper 观察，不自动注册或接入调度"
        if gate["passed"]
        else "未通过冻结研究门槛；归档失败指纹，不注册、不接入调度"
    )
    return f"""# 全球防守核心 × A股主线卫星 80/20 V2

- 严格共同区间：{audit['start_date']} 至 {audit['end_date']}，
  {audit['common_days']} 个交易日。
- Core 80%：全球防守三资产固定等权 V1。
- Satellite 20%：A股主线链动 V1；权重上限预先固定，不因回测结果调整。
- 两个袖套均读取 monitoring 净成本净值；不重跑或改变底层策略。
- 每月末形成调拨信号，下一交易日恢复 80/20，月内权重自然漂移。
- 基准调拨成本 10bps，累计成本 {allocation_cost:.6f} 净值单位，
  全期净值拖累 {cost_drag:.2%}。

| 阶段 | 袖套 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额 | 调拨换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

## 年度表现

| 年份 | 组合 | Core | Satellite | 组合最大回撤 |
|---|---:|---:|---:|---:|
{annual_rows}

## 独立性与尾部风险

- Core / Satellite 日收益相关性：{correlations['sleeve_full']:.3f}。
- 组合 / Quality 日收益相关性：{correlations['quality_full']:.3f}。
- 最差单日：{float(tail['worst_day']):.2%}。
- 95% Expected Shortfall：{float(tail['expected_shortfall_95']):.2%}。
- 最长水下期：{int(tail['max_underwater_days'])} 个共同交易日。
- 正收益年份：{int(tail['positive_years'])} / {int(tail['year_count'])}。

## 成本压力

| 场景 | 年化收益 | 最大回撤 | Sharpe | Calmar | 全期成本拖累 |
|---|---:|---:|---:|---:|---:|
| 10bps 基准 | {base['annualized_return']:.2%} | {base['max_drawdown']:.2%} | {base['sharpe']:.3f} | {base['calmar']:.3f} | {cost_drag:.2%} |
| 50bps 压力 | {stress['annualized_return']:.2%} | {stress['max_drawdown']:.2%} | {stress['sharpe']:.3f} | {stress['calmar']:.3f} | {stress_cost_drag:.2%} |

## 冻结门槛

{checks}

## 结论

{decision}。

本研究只验证两个既有净成本袖套的固定组合，不证明主线卫星自身已经解决
尾部不稳定问题。即使通过，也必须先做组合级前向 Paper，且不得自动启动
scheduler、生成实盘订单或替代底层策略。
"""
