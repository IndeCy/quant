"""五资产独立趋势槽位固定多折报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染趋势槽位、双动量对照、年度表现和冻结门槛。"""
    rows: list[str] = []
    for strategy_id, periods in result["period_metrics"].items():
        for period, item in periods.items():
            rows.append(
                f"| {strategy_id} | {period} | "
                f"{item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    annual = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    exposure = "\n".join(
        f"| {symbol} | {weight:.2%} |"
        for symbol, weight in result["average_exposure"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    delta = result["dual_momentum_delta"]
    return f"""# 五资产独立趋势槽位 V1

- 数据截止：{result['latest_date']}。
- 四个风险资产各固定25%槽位；MA60>MA120时持有，否则转5年国债。
- 不做相对排名、不集中Top2、不叠加额外波动率风险层。
- 与更新后双动量对照统一使用 qfq、M0 T+1、5bps、ETF免印花税。
- 与 Quality 日收益相关性：{result['quality_return_correlation']:.3f}。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual}

## 平均资产暴露

| 资产 | 平均目标权重 |
|---|---:|
{exposure}

## 相对双动量

- 全样本回撤改善：{delta['full_drawdown_improvement']:.2%}。
- 2015–2017回撤改善：{delta['early_drawdown_improvement']:.2%}。
- 年化收益变化：{delta['annual_return_change']:+.2%}。
- Sharpe变化：{delta['sharpe_change']:+.3f}。

## 固定门槛

{checks}

结论：{'通过研究门槛，仅进入独立前瞻确认' if result['gate']['passed'] else '终止并保留失败指纹，不注册生产'}。
"""
