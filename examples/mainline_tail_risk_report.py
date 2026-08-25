"""主线链动策略尾部风险法医报告。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """渲染主线与Quality对照的尾部风险证据。"""
    mainline = result["profiles"]["Mainline Chain"]
    quality = result["profiles"]["Quality Alpha"]
    gate = result["gate"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# 主线链动尾部风险法医 V1

- 数据截止：{result["latest_date"]}。
- 共同历史：{result["start_date"]} 至 {result["latest_date"]}，
  {result["common_days"]} 个交易日。
- 使用统一monitoring净成本净值，不重跑策略、不修改状态或风险层。
- 既有状态过滤研究已失败，本轮只解释尾部风险与恢复难度。

## 风险画像

| 指标 | Mainline Chain | Quality Alpha |
|---|---:|---:|
| 年化收益 | {mainline["annualized_return"]:.2%} | {quality["annualized_return"]:.2%} |
| 最大回撤 | {mainline["max_drawdown"]:.2%} | {quality["max_drawdown"]:.2%} |
| 年化波动 | {mainline["annualized_volatility"]:.2%} | {quality["annualized_volatility"]:.2%} |
| Sharpe | {mainline["sharpe"]:.3f} | {quality["sharpe"]:.3f} |
| 95% VaR | {mainline["var_95"]:.2%} | {quality["var_95"]:.2%} |
| 95% ES | {mainline["expected_shortfall_95"]:.2%} | {quality["expected_shortfall_95"]:.2%} |
| 最差单日 | {mainline["worst_day"]:.2%} | {quality["worst_day"]:.2%} |
| 最好10日占正对数收益 | {mainline["top10_positive_log_contribution"]:.1%} | {quality["top10_positive_log_contribution"]:.1%} |
| 去掉最好10日后年化 | {mainline["annualized_return_without_best_10_days"]:.2%} | {quality["annualized_return_without_best_10_days"]:.2%} |
| 正收益年份占比 | {mainline["positive_year_share"]:.1%} | {quality["positive_year_share"]:.1%} |
| 超过10%回撤次数 | {mainline["drawdown_episode_count"]} | {quality["drawdown_episode_count"]} |
| 最长总水下交易日 | {mainline["maximum_underwater_days"]} | {quality["maximum_underwater_days"]} |
| 最长谷底至恢复/截止交易日 | {mainline["maximum_recovery_days"]} | {quality["maximum_recovery_days"]} |

## Mainline重大回撤

| 峰值日 | 谷底日 | 恢复日 | 谷底回撤 | 水下交易日 | 谷底至恢复/截止日 | 已恢复 |
|---|---|---|---:|---:|---:|---|
{_episode_rows(mainline["episodes"][:10])}

## Mainline最好与最差交易日

最好10日：

{_day_rows(mainline["best_10_days"])}

最差10日：

{_day_rows(mainline["worst_10_days"])}

## 长期观察门槛

{checks}

- 判定：`{result["decision"]}`。
- {result["explanation"]}
- 该结论不自动退役策略，但在风险门槛通过前不得把其高收益视为稳定可承载Alpha。
"""


def _episode_rows(episodes: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"| {item['peak_date']} | {item['trough_date']} | "
        f"{item['recovery_date'] or '未恢复'} | {item['trough_drawdown']:.2%} | "
        f"{item['underwater_days']} | {item['recovery_days']} | "
        f"{'是' if item['recovered'] else '否'} |"
        for item in episodes
    )


def _day_rows(days: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"- {item['trade_date']}：{item['return']:+.2%}"
        for item in days
    )
