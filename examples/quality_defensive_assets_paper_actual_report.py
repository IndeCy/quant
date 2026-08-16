"""Quality防守袖套Paper实际账户差异报告。"""

from __future__ import annotations

from typing import Any


def render_actual_account_report(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """展示Paper实际账户与M0实际账户的持仓及净值差异。"""
    metric_rows = [
        _metric_row("M0", m0_metrics),
        _metric_row("Paper基准", paper_metrics["paper_baseline"]),
        _metric_row("Paper压力", paper_metrics["paper_stress"]),
    ]
    gap_rows = [
        _gap_row("Paper基准", diagnostics["paper_baseline"]),
        _gap_row("Paper压力", diagnostics["paper_stress"]),
    ]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality防守袖套 Paper 实际账户差异 V3

- 数据截止：{latest_date}，策略与V1/V2完全相同。
- V1记录绝对成交约束，V2记录相对理想目标的漂移，两个失败结论均保留。
- V3只回答Paper实际账户相对M0实际账户增加了多少持仓和净值偏差。

## 收益风险

| 口径 | 年化收益 | 最大回撤 | Sharpe | Calmar |
|---|---:|---:|---:|---:|
{chr(10).join(metric_rows)}

## 实际账户增量偏差

| 场景 | Paper/M0成功单 | 新增拒单率 | 平均持仓差 | 最大持仓差 | 最新持仓差 | 跟踪误差 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(gap_rows)}

## 冻结门槛

{checks}

结论：{'通过实际账户可执行性门槛，可创建长期Paper观察实例' if gate['passed'] else 'Paper实际账户仍显著偏离M0'}。
"""


def _metric_row(name: str, metrics: dict[str, float]) -> str:
    return (
        f"| {name} | {metrics['annualized_return']:.2%} | "
        f"{metrics['max_drawdown']:.2%} | {metrics['sharpe']:.3f} | "
        f"{metrics['calmar']:.3f} |"
    )


def _gap_row(name: str, metrics: dict[str, float]) -> str:
    return (
        f"| {name} | {metrics['successful_order_ratio_vs_m0']:.2%} | "
        f"{metrics['incremental_rejection_rate_vs_m0']:.2%} | "
        f"{metrics['average_actual_position_gap']:.2%} | "
        f"{metrics['max_actual_position_gap']:.2%} | "
        f"{metrics['latest_actual_position_gap']:.2%} | "
        f"{metrics['tracking_error']:.2%} |"
    )
