"""Quality 盈利底线过滤固定多折报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染候选、原策略对照、年度表现和冻结门槛。"""
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
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    delta = result["baseline_delta"]
    return f"""# Quality 盈利底线过滤 V1

- 数据截止：{result['latest_date']}。
- 原 Quality 80% + E/P 10% + B/P 10% 分数、Top20和月频不变。
- 仅剔除最近五个连续年报中最低 ROA 不大于 0 的公司。
- 先在完整基线截面评分，再过滤，盈利底线不参与加权。
- 候选与基线统一使用 M0 T+1、qfq、5bps 和
  `GRID(20日波动率>45%时仓位30%)`。

| 策略 | 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 相对原 Quality

- 全样本回撤改善：{delta['full_drawdown_improvement']:.2%}。
- 2015–2017 回撤改善：{delta['early_drawdown_improvement']:.2%}。
- Sharpe 变化：{delta['sharpe_change']:+.3f}。
- 年化收益变化：{delta['annual_return_change']:+.2%}。

## 固定门槛

{checks}

结论：{'仅进入独立前瞻验证' if result['gate']['passed'] else '终止并保留失败指纹，不注册生产'}。
"""
