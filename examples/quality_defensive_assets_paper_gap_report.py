"""Quality防守袖套相对M0增量执行偏差报告。"""

from __future__ import annotations

from typing import Any


def render_paper_gap_report(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
    gate: dict[str, Any],
    latest_date: str,
) -> str:
    """区分市场共同拦截与Paper新增执行问题。"""
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
    return f"""# Quality防守袖套 Paper 增量偏差 V2

- 数据截止：{latest_date}，策略和执行压力参数与V1完全相同。
- V1绝对拒单包含M0同样会拦截的停牌和涨跌停，并把T到T+1等待误计为漂移。
- V2不删除V1失败记录，只改用“Paper相对M0新增偏差”进行独立审计。

## 收益风险

| 口径 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(metric_rows)}

## 增量执行差异

| 场景 | Paper/M0成功单 | 新增拒单率 | 成交后平均漂移 | 最新漂移 | 跟踪误差 | 绝对填单率 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(gap_rows)}

## 冻结门槛

{checks}

结论：{'通过相对M0可执行性门槛，可创建长期Paper观察实例' if gate['passed'] else '仍存在不可接受的增量执行偏差'}。
"""


def _metric_row(name: str, metrics: dict[str, float]) -> str:
    return (
        f"| {name} | {metrics['annualized_return']:.2%} | "
        f"{metrics['max_drawdown']:.2%} | {metrics['sharpe']:.3f} | "
        f"{metrics['calmar']:.3f} | {metrics['annual_turnover']:.2f}x |"
    )


def _gap_row(name: str, metrics: dict[str, float]) -> str:
    return (
        f"| {name} | {metrics['successful_order_ratio_vs_m0']:.2%} | "
        f"{metrics['incremental_rejection_rate_vs_m0']:.2%} | "
        f"{metrics['average_post_execution_drift']:.2%} | "
        f"{metrics['latest_position_drift']:.2%} | "
        f"{metrics['tracking_error']:.2%} | "
        f"{metrics['fill_rate']:.2%} |"
    )
