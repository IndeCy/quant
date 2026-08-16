"""业绩预告与 Quality 等权确认的固定四折报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染候选、单腿对照、年度表现和冻结门槛。"""
    period_rows: list[str] = []
    for strategy_id, periods in result["period_metrics"].items():
        for period, item in periods.items():
            period_rows.append(
                f"| {strategy_id} | {period} | "
                f"{item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 业绩预告 × Quality 确认 V1

- 数据截止：{result['latest_date']}。
- 信号：正向业绩预告强度与年度 Quality 分数横截面秩各 50%。
- 组合：标准股票池交集、Top40、月频等权，不增加因子。
- 执行：M0 T+1、qfq、5bps；三条曲线统一使用
  `GRID(20日组合波动率>45%时仓位30%，否则100%)`。
- 研究约束：参数和门槛在收益扫描前冻结，不做后续变体。
- 候选平均仓位/降仓日/切换次数：
  {result['risk_summary']['average_exposure']:.1%} /
  {result['risk_summary']['reduced_days']:.0f} /
  {result['risk_summary']['event_count']:.0f}。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 相对预告单腿

- 回撤改善：{result['control_delta']['drawdown_improvement']:.2%}。
- Sharpe 变化：{result['control_delta']['sharpe_change']:+.3f}。
- 年化收益变化：{result['control_delta']['annual_return_change']:+.2%}。

## 固定门槛

{checks}

结论：{'通过研究门槛，仅进入独立前瞻验证' if result['gate']['passed'] else '未通过，保留失败指纹且不注册生产策略'}。
"""
