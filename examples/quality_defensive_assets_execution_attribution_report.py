"""Quality防守袖套Paper执行压力归因报告。"""

from __future__ import annotations

from typing import Any


SCENARIO_NAMES = {
    "baseline": "基准T+1/10bps/1%",
    "delay_only": "仅T+2延迟",
    "liquidity_only": "仅参与率0.2%",
    "slippage_only": "仅滑点20bps",
    "combined_stress": "组合压力",
}


def render_execution_attribution_report(
    metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
    attribution: dict[str, Any],
    latest_date: str,
) -> str:
    """展示单变量执行冲击及主导来源。"""
    rows = []
    for scenario_id, name in SCENARIO_NAMES.items():
        item = metrics[scenario_id]
        diag = diagnostics[scenario_id]
        rows.append(
            f"| {name} | {item['annualized_return']:.2%} | "
            f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
            f"{diag['tracking_error']:.2%} | "
            f"{diag['average_actual_position_gap']:.2%} | "
            f"{diag['latest_actual_position_gap']:.2%} |"
        )
    return f"""# Quality防守袖套 Paper 执行压力归因 V4

- 数据截止：{latest_date}。
- 所有场景使用同一策略、100万元资金、相同费用和100股整手。
- 每次只改变延迟、流动性或滑点中的一个条件，不选择新参数。

| 场景 | 年化收益 | 最大回撤 | Sharpe | 跟踪误差 | 平均持仓差 | 最新持仓差 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 归因

- 持仓偏差主导因素：{attribution['position_gap_driver']}。
- 收益损失主导因素：{attribution['return_loss_driver']}。
- 单因素最大平均持仓差：{attribution['max_single_position_gap']:.2%}。
- 单因素最大年化收益损失：{attribution['max_single_annual_loss']:.2%}。

结论：{attribution['conclusion']}。
"""
