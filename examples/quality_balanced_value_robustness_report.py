"""Quality Balanced Value 稳健性报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染首年依赖、滚动窗口和执行成本压力结果。"""
    period_rows = _metric_rows(result["period_metrics"])
    window_rows = _metric_rows(result["three_year_metrics"])
    annual_rows = _metric_rows(result["annual_metrics"])
    cost_rows = _metric_rows(result["cost_stress_metrics"])
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    summary = result["window_summary"]
    concentration = result["concentration"]
    return f"""# Quality Balanced Value V1 稳健性审计

- 数据截止：{result['latest_date']}。
- 策略定义、五个因子权重、Top20、月频和风险层保持不变。
- 本研究不选择参数，只检查首年依赖、完整三年窗口和执行成本压力。

## 全期与首年剔除

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 完整三年窗口

| 窗口 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{window_rows}

- 正收益窗口占比：{summary['positive_return_share']:.1%}。
- 正超额窗口占比：{summary['positive_excess_share']:.1%}。
- 窗口 Sharpe 中位数：{summary['median_sharpe']:.3f}。
- 最差窗口最大回撤：{summary['worst_drawdown']:.2%}。

## 年度收益

| 年份 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{annual_rows}

- 正收益年度：{concentration['positive_year_count']:.0f}。
- 最好一年占全部正对数收益：{concentration['top1_positive_log_contribution']:.1%}。
- 最好三年占全部正对数收益：{concentration['top3_positive_log_contribution']:.1%}。

## 成本压力

| 滑点 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{cost_rows}

## 预注册门禁

{checks}

## 结论

决策：`{result['decision']}`。本研究不修改生产策略定义。
"""


def _metric_rows(metrics: dict[str, dict[str, float]]) -> str:
    """统一渲染指标表。"""
    return "\n".join(
        f"| {label} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for label, item in metrics.items()
    )
