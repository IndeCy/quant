"""沪深300、黄金和国债三资产等权研究报告。"""

from __future__ import annotations

from typing import Any


ASSET_NAMES = {
    "510300.SH": "沪深300ETF",
    "518880.SH": "黄金ETF",
    "511010.SH": "5年国债ETF",
}


def render_report(result: dict[str, Any]) -> str:
    """渲染固定口径、多折对照与晋级门槛。"""
    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in result["period_metrics"].items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    comparison_rows = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} |"
        for name, item in result["full_comparison"].items()
    )
    holding_rows = "\n".join(
        f"| {item['symbol']} | {ASSET_NAMES[item['symbol']]} | "
        f"{item['target_weight']:.1%} |"
        for item in result["latest_holdings"]
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 三资产固定等权全天候策略 V1

- 数据共同截止：{result['latest_date']}。
- 固定资产：沪深300ETF、黄金ETF、5年国债ETF，各三分之一。
- 月频恢复等权，不做趋势选择，不叠加风险覆盖层。
- 执行口径：统一qfq、M0 T+1、5bps，ETF免印花税。
- 与 Quality 日收益相关性：{result['quality_return_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 同口径对照

| 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
{comparison_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 最新目标

| 代码 | 资产 | 目标权重 |
|---|---|---:|
{holding_rows}

## 固定研究门槛

{checks}

结论：{'通过固定多折门槛，仅允许进入前瞻Paper确认' if result['gate']['passed'] else '未通过固定门槛，终止该路线'}。
"""
