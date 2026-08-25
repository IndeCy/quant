"""黄金国债等权防守策略独立确认报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染多折、年度、独立性和固定门槛。"""
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
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 黄金国债等权防守策略 V1

- 数据截止：{result['latest_date']}。
- 固定配置：黄金ETF 50%、5年国债ETF 50%，月频恢复等权。
- 执行：统一基金qfq、M0 T+1、5bps、ETF免印花税。
- 不使用选股因子、不做趋势判断、不叠加额外风险层。
- 与 Quality 日收益相关性：
  {result['quality_return_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{periods}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 固定门槛

{checks}

结论：{'通过独立确认，可进入前瞻Paper观察' if result['gate']['passed'] else '未通过，不创建独立观察策略'}。
"""
