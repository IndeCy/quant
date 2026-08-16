"""因子动物园共同模式审计报告。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """渲染共同收益源和中盘风格归因证据。"""
    raw = result["raw_return_summary"]
    excess = result["excess_return_summary"]
    style = result["style_attribution"]
    residual = style["residual_correlation_summary"]
    regression = style["csi500_spread_regression"]
    gate_rows = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 因子动物园共同模式审计 V1

- 数据截止：{result["as_of_date"]}。
- 实验仓库有效因子家族：{result["eligible_experiment_count"]} 个。
- 2015至{result["latest_year"]}年度数据完整家族：
  {result["complete_experiment_count"]} 个。
- 只读取结构化实验结果和统一qfq ETF行情，不重跑或修改任何策略。

## 有效独立性

| 指标 | 策略年度收益 | 相对510300年度超额 | 剔除中证500相对沪深300价差后 |
|---|---:|---:|---:|
| 平均两两相关 | {raw["average_pairwise_correlation"]:.3f} | {excess["average_pairwise_correlation"]:.3f} | {residual["average_pairwise_correlation"]:.3f} |
| 中位两两相关 | {raw["median_pairwise_correlation"]:.3f} | {excess["median_pairwise_correlation"]:.3f} | {residual["median_pairwise_correlation"]:.3f} |
| 第一共同成分解释度 | {raw["first_component_variance_share"]:.1%} | {excess["first_component_variance_share"]:.1%} | {residual["first_component_variance_share"]:.1%} |
| 有效独立押注数 | {raw["effective_breadth"]:.2f} | {excess["effective_breadth"]:.2f} | {residual["effective_breadth"]:.2f} |

策略名字虽然不同，但年度超额收益主要由同一个共同成分驱动。
剔除市场基准后该现象仍存在，因此不能解释为单纯沪深300 Beta。

## 风格归因

- 共同超额与“中证500－沪深300”相关：
  {style["common_correlation_to_csi500_spread"]:.3f}。
- 共同超额与“创业板－沪深300”相关：
  {style["common_correlation_to_chinext_spread"]:.3f}。
- 中证500价差对共同超额的解释度：
  {regression["r_squared"]:.1%}，斜率
  {regression["slope"]:.2f}。
- 逐年剔除后的最低相关/最低解释度：
  {style["leave_one_year_out_min_correlation"]:.3f} /
  {style["leave_one_year_out_min_r_squared"]:.1%}。
- {style["strategy_correlation_ge_070_share"]:.1%}
  的完整实验与中证500价差相关不低于0.70。

这强烈支持历史因子动物园的主要共同风险源是中盘风格暴露，
而不是31个独立Alpha。
剔除该暴露后有效押注数虽从
{excess["effective_breadth"]:.2f} 提升至
{residual["effective_breadth"]:.2f}，剩余独立性仍然有限。

## 年度同步性

| 年份 | 因子共同超额 | 中证500－沪深300 | 创业板－沪深300 | 正超额实验占比 |
|---:|---:|---:|---:|---:|
{_year_rows(style["yearly_common_mode"])}

## 中盘暴露最低的实验

| 实验 | 与中证500价差相关 |
|---|---:|
{_correlation_rows(style["strategy_correlations"][:10])}

## 中盘暴露最高的实验

| 实验 | 与中证500价差相关 |
|---|---:|
{_correlation_rows(list(reversed(style["strategy_correlations"][-10:])))}

## 冻结门槛

{gate_rows}

- 判定：`{result["decision"]}`。
- 后续新候选必须先报告中证500相对沪深300暴露，并在剔除该暴露后证明独立性；
  只更换因子名称、但继续押注同一中盘共同模式，不再视为新增Alpha来源。
- 本研究使用年度数据识别长期共同模式，不能替代逐期市值和行业暴露审计。
"""


def _year_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"| {item['year']} | {item['common_excess_return']:.2%} | "
        f"{item['csi500_minus_hs300']:.2%} | "
        f"{item['chinext_minus_hs300']:.2%} | "
        f"{item['positive_excess_share']:.1%} |"
        for item in rows
    )


def _correlation_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"| {item['experiment_id']} | {item['correlation']:.3f} |"
        for item in rows
    )
