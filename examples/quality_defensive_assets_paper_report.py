"""Quality防守袖套Paper可执行性报告。"""

from __future__ import annotations

from typing import Any


def render_paper_report(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """展示M0、正常Paper和压力Paper的净值与执行差异。"""
    rows = [
        _metric_row("M0基准", m0_metrics),
        _metric_row("Paper基准", paper_metrics["paper_baseline"]),
        _metric_row("Paper压力", paper_metrics["paper_stress"]),
    ]
    diagnostic_rows = [
        _diagnostic_row("Paper基准", diagnostics["paper_baseline"]),
        _diagnostic_row("Paper压力", diagnostics["paper_stress"]),
    ]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Quality防守袖套 Paper 可执行性 V1

- 数据截止：{latest_date}，初始资金100万元。
- 基准Paper：T+1、10bps、成交量参与率1%、万三佣金、最低5元。
- 压力Paper：T+2、20bps、成交量参与率0.2%，其余费用相同。
- 股票卖出收千一印花税，黄金与国债ETF免印花税，全部100股整手。
- 部分成交剩余数量不自动追单，作为保守执行压力。

## 收益与风险

| 口径 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 | 总执行成本 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 执行偏差

| 场景 | 填单率 | 拒单率 | 部分成交率 | 平均持仓漂移 | 最大漂移 | 跟踪误差 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(diagnostic_rows)}

## 冻结门槛

{checks}

结论：{'通过历史Paper可执行性门槛，可创建长期观察实例' if gate['passed'] else '执行偏差不可接受，不注册Paper'}。
"""


def _metric_row(name: str, metrics: dict[str, float]) -> str:
    """格式化收益风险指标。"""
    return (
        f"| {name} | {metrics['annualized_return']:.2%} | "
        f"{metrics['max_drawdown']:.2%} | {metrics['sharpe']:.3f} | "
        f"{metrics['calmar']:.3f} | {metrics['annual_turnover']:.2f}x | "
        f"{metrics.get('total_execution_cost', 0.0):,.0f} |"
    )


def _diagnostic_row(name: str, metrics: dict[str, float]) -> str:
    """格式化成交与跟踪偏差。"""
    return (
        f"| {name} | {metrics['fill_rate']:.2%} | "
        f"{metrics['rejection_rate']:.2%} | "
        f"{metrics['partial_order_rate']:.2%} | "
        f"{metrics['average_position_drift']:.2%} | "
        f"{metrics['max_position_drift']:.2%} | "
        f"{metrics['tracking_error']:.2%} |"
    )
