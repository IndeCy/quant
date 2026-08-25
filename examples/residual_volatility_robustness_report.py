"""低特质波动稳健性与市场归因报告。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """渲染固定参数复核结果。"""
    source = result["source_classification"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in source["checks"].items()
    )
    return f"""# 120日低特质波动稳健性与Beta归因

- 数据截止：{result["latest_date"]}。
- 固定定义：120日相对510300残差波动率，Top40月频等权。
- 固定执行：qfq、M0 T+1、GRID风险层、基准滑点5bps。
- 本研究不改变因子窗口、TopN、股票池或风险层。
- 与Quality日收益相关性：{result["quality_return_correlation"]:.3f}。
- 普通60日低波Top40月度重叠中位数：{result["diagnostics"]["median_top40_overlap_with_lowvol"]:.1%}。

## 区间稳健性

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{_metric_rows(result["period_metrics"])}

## 成本压力

| 滑点 | 年化收益 | 最大回撤 | Sharpe | 超额收益 | 执行成本影响 |
|---|---:|---:|---:|---:|---:|
{_cost_rows(result["cost_stress_metrics"])}

## 市场回归归因

| 区间 | Beta | 年化Alpha | R² | 上行捕获 | 下行捕获 | 跟踪误差 | 信息比率 |
|---|---:|---:|---:|---:|---:|---:|---:|
{_attribution_rows(result["market_attribution"])}

非重叠窗口中：

- Alpha为正比例：{result["market_attribution_summary"]["positive_alpha_share"]:.1%}
- 年化Alpha中位数：{result["market_attribution_summary"]["median_annualized_alpha"]:.2%}
- Beta中位数：{result["market_attribution_summary"]["median_beta"]:.3f}
- 最大Beta：{result["market_attribution_summary"]["maximum_beta"]:.3f}

## 稳健性限制

- 剔除2015后年化收益降至{result["period_metrics"]["without_2015"]["annualized_return"]:.2%}，
  回归Alpha降至{result["market_attribution"]["without_2015"]["annualized_alpha"]:.2%}。
- 2018至2020折年化收益为{result["period_metrics"]["fold_2018_2020"]["annualized_return"]:.2%}，
  回归Alpha为{result["market_attribution"]["fold_2018_2020"]["annualized_alpha"]:.2%}。
- 20bps压力下最大回撤扩大到{result["cost_stress_metrics"]["20bps"]["max_drawdown"]:.2%}。
- 以上是结果后的稳健性解释，不改变预注册来源判定门槛。

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe | 超额收益 |
|---:|---:|---:|---:|---:|
{_annual_rows(result["annual_metrics"])}

## 来源判定

{checks}

- 标签：`{source["label"]}`
- 解释：{source["explanation"]}

结论：保留为防御风险溢价研究证据，但不作为独立Alpha注册生产，
也不进入历史参数优化。
"""


def _metric_rows(metrics: Mapping[str, Mapping[str, float]]) -> str:
    return "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in metrics.items()
    )


def _cost_rows(metrics: Mapping[str, Mapping[str, float]]) -> str:
    return "\n".join(
        f"| {scenario} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['excess_return']:.2%} | {item['execution_cost_impact']:.2%} |"
        for scenario, item in metrics.items()
    )


def _attribution_rows(metrics: Mapping[str, Mapping[str, float]]) -> str:
    return "\n".join(
        f"| {period} | {item['beta']:.3f} | "
        f"{item['annualized_alpha']:.2%} | {item['r_squared']:.3f} | "
        f"{item['up_capture']:.1%} | {item['down_capture']:.1%} | "
        f"{item['tracking_error']:.2%} | {item['information_ratio']:.3f} |"
        for period, item in metrics.items()
    )


def _annual_rows(metrics: Mapping[str, Mapping[str, float]]) -> str:
    return "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['excess_return']:.2%} |"
        for year, item in metrics.items()
    )
