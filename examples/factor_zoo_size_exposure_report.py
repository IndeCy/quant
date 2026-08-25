"""因子动物园代表持仓市值暴露报告。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """渲染收益风格归因与持仓市值证据。"""
    comparison = result["group_comparison"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return f"""# 因子动物园持仓级市值暴露审计 V1

- 数据截止：{result["as_of_date"]}。
- 代表策略在查看持仓前固定为两组，各2个。
- 市值代理：信号日未复权收盘价 × 当时已披露最新总股本。
- 市值分位在同日标准可投A股池内计算，0代表最小、1代表最大。
- 本研究只重建原定义历史持仓，不运行收益优化、不修改策略。

## 代表策略

| 策略 | 代表组 | 年度超额与中证500价差相关 | 信号期 | 持仓记录 | 市值覆盖 | 逐期市值分位中位数 | 底部25%占比 | 底部50%占比 | 顶部25%占比 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
{_strategy_rows(result["strategy_exposures"])}

## 组间比较

- 高相关组逐期市值分位中位数：
  {comparison["high_group_median_size_percentile"]:.1%}。
- 低相关组逐期市值分位中位数：
  {comparison["low_group_median_size_percentile"]:.1%}。
- 低相关组相对高相关组的市值分位差：
  {comparison["low_minus_high_size_percentile"]:.1%}。
- 高相关组底部半区占比：
  {comparison["high_group_bottom_half_share"]:.1%}；
  低相关组：{comparison["low_group_bottom_half_share"]:.1%}。
- 年度中盘相关与实际市值分位的Spearman：
  {comparison["style_corr_vs_size_spearman"]:.3f}。

## 冻结门槛

{checks}

- 判定：`{result["decision"]}`。
- {result["explanation"]}
- 该结论只验证四个预先冻结的代表策略，不能直接外推为全部30个实验的逐期持仓证明。
"""


def _strategy_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    labels = {
        "HIGH_MIDCAP_CORRELATION": "高相关",
        "LOW_MIDCAP_CORRELATION": "低相关",
    }
    return "\n".join(
        f"| {item['strategy_id']} | {labels[item['style_group']]} | "
        f"{item['style_correlation']:.3f} | {item['signal_periods']} | "
        f"{item['holding_records']} | {item['coverage']:.1%} | "
        f"{item['median_period_market_cap_percentile']:.1%} | "
        f"{item['bottom_quartile_share']:.1%} | "
        f"{item['bottom_half_share']:.1%} | "
        f"{item['top_quartile_share']:.1%} |"
        for item in rows
    )
