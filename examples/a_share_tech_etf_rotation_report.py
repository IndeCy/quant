"""A股科技ETF中频轮动研究报告。"""

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
    holdings = "\n".join(
        f"| {item['symbol']} | {item['name']} | "
        f"{item['target_weight']:.1%} | {item['role']} |"
        for item in result["latest_holdings"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    conclusion = (
        "通过冻结门槛，仅允许研究级前向观察"
        if result["gate"]["passed"]
        else "未通过冻结门槛，归档且不注册"
    )
    return f"""# A股科技ETF周频相对强度轮动 V1

- 数据共同截止：{result['latest_date']}。
- 固定池：半导体、通信、计算机、人工智能、科技龙头ETF。
- 每周最后一个交易日计算20日相对强度；只允许正动量且站上MA60的ETF入选。
- 前两名各40%，固定20%五年国债；空余槽位全部回到国债。
- 信号下一交易日经M0执行，统一qfq、10bps，ETF免印花税。
- 不做窗口、TopN、权重或调仓频率网格。
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

## 最新目标

| 代码 | 资产 | 权重 | 角色 |
|---|---|---:|---|
{holdings}

## 尾部与状态

- 年化波动：{result['diagnostics']['annualized_volatility']:.2%}
- 最差单日：{result['diagnostics']['worst_day']:.2%}
- 95% Expected Shortfall：{result['diagnostics']['expected_shortfall_95']:.2%}
- 最长水下期：{result['diagnostics']['max_underwater_days']}个交易日
- 平均风险资产目标仓位：{result['diagnostics']['average_risky_target_weight']:.1%}

## 冻结门槛

{checks}

结论：{conclusion}。
"""
