"""当前观察策略的收益源地图报告。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(
    result: Mapping[str, Any],
    strategy_ids: Sequence[str],
) -> str:
    """渲染相关、残差和风险分散证据。"""
    return f"""# 当前观察策略 Alpha 来源地图 V1

- 数据截止：{result["latest_date"]}。
- 严格共同历史：{result["start_date"]} 至 {result["latest_date"]}，
  {result["common_days"]} 个交易日。
- 仅纳入拥有至少1000个共同净值观测的正式观察策略。
- 收益来自统一 monitoring 净成本事实表；510300基准取Quality统一曲线。
- 本研究不生成新组合、不选择权重、不修改任何策略。

## 策略表现

| 策略 | 年化收益 | 最大回撤 | 年化波动 | Sharpe | Beta | 年化回归Alpha | 上行捕获 | 下行捕获 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{_summary_rows(result["strategy_summaries"], strategy_ids)}

## 普通日收益相关

{_matrix_table(result["return_correlation"], strategy_ids)}

## 510300下跌日相关

{_matrix_table(result["downside_correlation"], strategy_ids)}

## 剔除510300 Beta后的残差相关

{_matrix_table(result["residual_correlation"], strategy_ids)}

## 两两风险分散

| 左策略 | 右策略 | 普通相关 | 50/50波动分散率 | 市场下跌日共同亏损比例 |
|---|---|---:|---:|---:|
{_pair_rows(result["pairwise_risk_map"])}

## 独立收益源

- 普通相关矩阵有效押注数：{result["effective_bets"]["return"]:.2f} / {len(strategy_ids)}。
- 下跌日相关矩阵有效押注数：{result["effective_bets"]["downside"]:.2f} / {len(strategy_ids)}。
- Beta残差相关矩阵有效押注数：{result["effective_bets"]["residual"]:.2f} / {len(strategy_ids)}。
- 相关阈值0.75形成的收益源簇：{result["clusters"]}。

## 研究结论

- 判定：`{result["decision"]}`。
- {result["explanation"]}
- 下一类候选必须优先证明与现有收益源的残差相关低于0.75，
  再进入未来收益回测；仅改变Quality内部排序不再视为新增Alpha来源。
"""


def _summary_rows(
    summaries: Mapping[str, Mapping[str, float]],
    strategy_ids: Sequence[str],
) -> str:
    return "\n".join(
        f"| {strategy_id} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['annualized_volatility']:.2%} | "
        f"{item['sharpe']:.3f} | {item['beta']:.3f} | "
        f"{item['annualized_alpha']:.2%} | {item['up_capture']:.1%} | "
        f"{item['down_capture']:.1%} |"
        for strategy_id in strategy_ids
        for item in [summaries[strategy_id]]
    )


def _matrix_table(
    matrix: Mapping[str, Mapping[str, float]],
    strategy_ids: Sequence[str],
) -> str:
    header = "| 策略 | " + " | ".join(strategy_ids) + " |\n"
    separator = "|---|" + "---:|" * len(strategy_ids) + "\n"
    rows = "\n".join(
        "| "
        + strategy_id
        + " | "
        + " | ".join(f"{matrix[strategy_id][other]:.3f}" for other in strategy_ids)
        + " |"
        for strategy_id in strategy_ids
    )
    return header + separator + rows


def _pair_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"| {item['left']} | {item['right']} | {item['correlation']:.3f} | "
        f"{item['diversification_ratio']:.3f} | "
        f"{item['downside_joint_loss_share']:.1%} |"
        for item in rows
    )
