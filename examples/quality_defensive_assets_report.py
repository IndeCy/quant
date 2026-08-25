"""Quality防守资产研究的Markdown报表渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    correlations: dict[str, float],
    risk_path: dict[str, Any],
    latest_date: str,
    *,
    blend_id: str,
) -> str:
    """生成核心、防守袖套和固定组合的对比报告。"""
    rows: list[str] = []
    for strategy_id, period_metrics in metrics.items():
        for period, item in period_metrics.items():
            rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in annual[blend_id].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality + 黄金国债 70/15/15 V1

- 数据截止：{latest_date}。
- 固定证券级组合：Quality Balanced Value 70%、黄金ETF 15%、5年国债ETF 15%。
- 三类证券统一qfq、T+1、M0和5bps；股票卖出收印花税，ETF免印花税。
- 核心与组合使用相同20日波动率风险层，防守袖套仅用于归因。
- 防守袖套与Quality相关性：{correlations['defensive_core']:.3f}；
  组合与Quality相关性：{correlations['blend_core']:.3f}。
- 2015年核心首次降仓：{risk_path['core']['first_reduced_date_2015']}；
  混合组合首次降仓：{risk_path['blend']['first_reduced_date_2015']}，
  晚{risk_path['blend_trigger_delay_trading_days']}个交易日。

| 策略 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 组合年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定门槛

{checks}

- 相对核心回撤改善：{gate['drawdown_improvement']:.2%}。
- 相对核心年化收益差：{gate['annual_return_shortfall']:.2%}。

风险路径解释：防守资产压低了组合触发前的20日波动率，使同一45%阈值更晚生效。
本结果说明固定配置与非线性风险覆盖层不能分别验证后再直接拼接。

结论：{'进入独立前瞻确认，不注册生产' if gate['passed'] else '终止，不进入生产'}。
"""
