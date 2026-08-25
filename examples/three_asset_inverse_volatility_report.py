"""三资产逆波动风险预算研究报告。"""

from __future__ import annotations

from typing import Any


ASSET_NAMES = {
    "510300.SH": "沪深300ETF",
    "518880.SH": "黄金ETF",
    "511010.SH": "5年国债ETF",
}


def render_report(result: dict[str, Any]) -> str:
    """渲染多折、年度、权重诊断和固定门槛。"""
    periods = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in result["period_metrics"].items()
    )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    comparisons = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    exposures = "\n".join(
        f"| {symbol} | {ASSET_NAMES[symbol]} | "
        f"{item['average_weight']:.1%} | {item['latest_weight']:.1%} | "
        f"{item['maximum_weight']:.1%} |"
        for symbol, item in result["weight_diagnostics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 三资产逆波动风险预算 V1

- 数据共同截止：{result['latest_date']}。
- 资产：沪深300ETF、黄金ETF、5年国债ETF。
- 月末按过去60个交易日年化波动率倒数归一化，无杠杆、无权重上限。
- 使用统一qfq、M0 T+1、5bps，ETF免印花税，不叠加风险覆盖层。
- 与 Quality 日收益相关性：{result['quality_return_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{periods}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{comparisons}

## 权重诊断

| 代码 | 资产 | 平均权重 | 最新权重 | 历史最高权重 |
|---|---|---:|---:|---:|
{exposures}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 固定门槛

{checks}

结论：{'通过固定多折门槛，仅允许进入前瞻Paper确认' if result['gate']['passed'] else '未通过固定门槛，终止该路线'}。
"""
