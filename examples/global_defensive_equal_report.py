"""全球防守三资产固定等权研究报告。"""

from __future__ import annotations

from typing import Any


ASSET_NAMES = {
    "513500.SH": "标普500ETF",
    "518880.SH": "黄金ETF",
    "511010.SH": "5年国债ETF",
}


def render_report(result: dict[str, Any]) -> str:
    """渲染多折表现、资产独立性和预注册门槛。"""
    periods = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for name, item in result["period_metrics"].items()
    )
    comparisons = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['excess_return']:.2%} |"
        for year, item in result["annual_metrics"].items()
    )
    correlations = "\n".join(
        f"| {left} | {right} | {value:.3f} |"
        for left, row in result["asset_return_correlations"].items()
        for right, value in row.items()
        if left < right
    )
    holdings = "\n".join(
        f"| {item['symbol']} | {ASSET_NAMES[item['symbol']]} | "
        f"{item['target_weight']:.1%} |"
        for item in result["latest_holdings"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    full = result["period_metrics"]["full"]
    return f"""# 全球防守三资产固定等权 V1

- 数据共同截止：{result['latest_date']}。
- 固定资产：标普500ETF、黄金ETF、5年国债ETF，各三分之一。
- 月频恢复等权，不做动量选择，不叠加风险覆盖层。
- 执行口径：统一qfq、M0 T+1、5bps，ETF免印花税。
- 研究目的：寻找独立于A股中盘共同模式的跨资产配置收益。

## 核心结果

| 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 执行成本影响 |
|---:|---:|---:|---:|---:|---:|
| {full['annualized_return']:.2%} | {full['max_drawdown']:.2%} | {full['sharpe']:.3f} | {full['calmar']:.3f} | {full['excess_return']:.2%} | {full['execution_cost_impact']:.2%} |

## 多折表现

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{periods}

## 固定对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
{comparisons}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe | 超额收益 |
|---:|---:|---:|---:|---:|
{annual}

## 独立性

- 与 Quality 日收益相关性：{result['quality_return_correlation']:.3f}。

| 资产A | 资产B | 日收益相关性 |
|---|---|---:|
{correlations}

## 最新目标

| 代码 | 资产 | 目标权重 |
|---|---|---:|
{holdings}

## 预注册门槛

{checks}

结论：{'通过固定多折门槛，仅允许进入前瞻Paper确认' if result['gate']['passed'] else '未通过固定门槛，终止该路线且不生成参数变体'}。
"""
