"""Quality核心袖套风险预算研究的Markdown报告。"""

from __future__ import annotations

from typing import Any


def render_scoped_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    annual: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    latest_date: str,
    *,
    scoped_id: str,
    core_id: str,
    whole_id: str,
) -> str:
    """渲染核心、整组合覆盖层和袖套级覆盖层对比。"""
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
        for year, item in annual[scoped_id].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    core_full = metrics[core_id]["full"]
    whole_full = metrics[whole_id]["full"]
    scoped_full = metrics[scoped_id]["full"]
    return f"""# Quality防守袖套风险预算 V2

- 数据截止：{latest_date}。
- 固定预算：Quality 70%、黄金ETF 15%、5年国债ETF 15%。
- 正常期总仓位100%；核心风险层触发后为Quality 21%、防守30%、现金49%。
- 风险参数保持20日、45%阈值、核心降至30%，不修改Alpha和M0。

| 策略 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定门槛

{checks}

- 相对纯核心回撤变化：{scoped_full['max_drawdown'] - core_full['max_drawdown']:.2%}。
- 相对整组合覆盖层回撤变化：{scoped_full['max_drawdown'] - whole_full['max_drawdown']:.2%}。
- 相对纯核心年化收益差：{core_full['annualized_return'] - scoped_full['annualized_return']:.2%}。

结论：{'通过研究门槛，仅进入前瞻确认' if gate['passed'] else '未通过门槛，不注册生产'}。
"""
