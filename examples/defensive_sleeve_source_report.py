"""Quality防守资产的袖套来源归因报告。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(
    result: Mapping[str, Any],
    labels: Sequence[str],
) -> str:
    """展示袖套独立性、方差贡献和策略级同源原因。"""
    risk = result["risk_contributions"]
    decision = result["dominance"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in decision["checks"].items()
    )
    return f"""# Quality防守资产袖套来源归因 V1

- 数据截止：{result["latest_date"]}。
- 共同历史：{result["start_date"]} 至 {result["latest_date"]}，
  {result["common_days"]} 个交易日。
- 固定预算保持Quality 70%、黄金ETF 15%、5年国债ETF 15%。
- Quality核心与最终策略来自同一次证券级回测产物；
  黄金、国债使用统一复权ETF曲线。
- 固定预算曲线仅用于风险归因，不构成新策略或可交易回测。

## 袖套表现与市场归因

| 袖套 | 年化收益 | 最大回撤 | 年化波动 | Sharpe | Beta | 年化Alpha | 上行捕获 | 下行捕获 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{_summary_rows(result["summaries"], labels)}

## 普通收益相关

{_matrix_table(result["return_correlation"], labels)}

## 剔除510300 Beta后的残差相关

{_matrix_table(result["residual_correlation"], labels)}

## 固定预算风险贡献

- 组合年化波动：{risk["portfolio_annualized_volatility"]:.2%}。
- 波动分散率：{risk["diversification_ratio"]:.3f}。

| 袖套 | 配置权重 | 独立年化波动 | 组合方差贡献 |
|---|---:|---:|---:|
{_risk_rows(result["weights"], risk, ["Quality Core", "Gold", "Bond"])}

## 策略级解释

- 最终防守策略与Quality核心普通相关：
  {result["actual_core_return_correlation"]:.3f}。
- 最终防守策略与Quality核心Beta残差相关：
  {result["actual_core_residual_correlation"]:.3f}。
- 固定预算归因曲线与实际策略相关：
  {result["fixed_actual_return_correlation"]:.3f}。

{checks}

- 判定：`{decision["label"]}`。
- {decision["explanation"]}
- 黄金和国债提供的是风险缓冲，不应在策略数量统计中被误认为新的股票Alpha。
"""


def _summary_rows(
    summaries: Mapping[str, Mapping[str, float]],
    labels: Sequence[str],
) -> str:
    return "\n".join(
        f"| {label} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['annualized_volatility']:.2%} | "
        f"{item['sharpe']:.3f} | {item['beta']:.3f} | "
        f"{item['annualized_alpha']:.2%} | {item['up_capture']:.1%} | "
        f"{item['down_capture']:.1%} |"
        for label in labels
        for item in [summaries[label]]
    )


def _matrix_table(
    matrix: Mapping[str, Mapping[str, float]],
    labels: Sequence[str],
) -> str:
    header = "| 袖套 | " + " | ".join(labels) + " |\n"
    separator = "|---|" + "---:|" * len(labels) + "\n"
    rows = "\n".join(
        "| "
        + label
        + " | "
        + " | ".join(f"{matrix[label][other]:.3f}" for other in labels)
        + " |"
        for label in labels
    )
    return header + separator + rows


def _risk_rows(
    weights: Mapping[str, float],
    risk: Mapping[str, Any],
    labels: Sequence[str],
) -> str:
    return "\n".join(
        f"| {label} | {weights[label]:.1%} | "
        f"{risk['standalone_annualized_volatility'][label]:.2%} | "
        f"{risk['risk_contribution_share'][label]:.1%} |"
        for label in labels
    )
