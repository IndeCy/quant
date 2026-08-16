"""纳指、黄金、国债增长防守平衡组合报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
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
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    conclusion = (
        "通过冻结门槛，仅允许前向研究观察"
        if result["gate"]["passed"]
        else "未通过冻结门槛，归档且不注册"
    )
    return f"""# 纳指50×黄金25×国债25增长防守平衡 V1

- 数据共同截止：{result['latest_date']}。
- 固定持有纳指100ETF 50%、黄金ETF 25%、五年国债ETF 25%。
- 月末恢复固定权重；不择时、不做权重搜索、不使用杠杆或风险层。
- 信号下一交易日经M0执行，统一qfq、5bps，ETF免印花税。
- 对照：纳指/黄金60/40、全球防守三资产等权、场内标普500。
- 与Quality日收益相关性：{result['diagnostics']['quality_correlation']:.3f}。

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

## 尾部诊断

- 年化波动：{result['diagnostics']['annualized_volatility']:.2%}
- 最差单日：{result['diagnostics']['worst_day']:.2%}
- 95% Expected Shortfall：{result['diagnostics']['expected_shortfall_95']:.2%}
- 最长水下期：{result['diagnostics']['max_underwater_days']}个交易日

## 冻结门槛

{checks}

结论：{conclusion}。
"""
