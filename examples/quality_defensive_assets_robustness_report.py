"""Quality防守袖套鲁棒性确认报告。"""

from __future__ import annotations

from typing import Any


SCENARIO_NAMES = {
    "baseline_70_15_15": "基准70/15/15",
    "neighbor_60_20_20": "相邻60/20/20",
    "neighbor_80_10_10": "相邻80/10/10",
    "gold_only_70_30": "黄金单袖套70/30",
    "bond_only_70_30": "国债单袖套70/30",
    "slippage_10bps": "滑点10bps",
    "slippage_20bps": "滑点20bps",
    "risk_delay_one_day": "风险信号额外延迟1天",
}


def render_robustness_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """展示全部冻结场景，不进行事后最优版本选择。"""
    rows = []
    for scenario_id, name in SCENARIO_NAMES.items():
        item = metrics[scenario_id]["full"]
        rows.append(
            f"| {name} | {item['annualized_return']:.2%} | "
            f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
            f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
            f"{item['annual_turnover']:.2f}x |"
        )
    fold_rows = []
    for period, item in metrics["baseline_70_15_15"].items():
        fold_rows.append(
            f"| {period} | {item['annualized_return']:.2%} | "
            f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality防守袖套鲁棒性确认 V1

- 数据截止：{latest_date}。
- 主方案固定为Quality 70%、黄金15%、国债15%，风险层仅管理Quality核心。
- 本研究不选择表现最好的场景，只用相邻权重和执行压力测试淘汰主方案。
- 所有场景保持qfq、财务as-of、M0和T+1。

## 场景结果

| 场景 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 主方案分段

| 阶段 | 年化收益 | 最大回撤 | Sharpe |
|---|---:|---:|---:|
{chr(10).join(fold_rows)}

## 冻结门槛

{checks}

- 全场景最低年化：{gate['min_annualized_return']:.2%}。
- 全场景最差回撤：{gate['worst_max_drawdown']:.2%}。
- 全场景最低Sharpe：{gate['min_sharpe']:.3f}。

结论：{'通过鲁棒性确认，可进入长期Paper观察' if gate['passed'] else '鲁棒性不足，不进入Paper'}。
"""
