"""机构席位数据可行性报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """生成机构席位数据门禁报告。"""
    diagnostics = result["diagnostics"]
    distribution = result["latest_distribution"]
    correlations = result["median_correlations"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 机构席位净买入强度数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 合格月份（全样本/2025年至今）：{result['qualified_month_share']:.2%} /
  {result['locked_qualified_month_share']:.2%}。
- 正净买入候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}；
  Top20 事件日中位数：{result['top20_median_event_days']:.1f}。
- 交易日同步成功/空结果占比：{diagnostics['successful_trade_day_share']:.2%} /
  {diagnostics['empty_trade_day_share']:.2%}；单日最多原始行：
  {diagnostics['max_raw_rows']:.0f}。
- 原始/去重后行数：{diagnostics['raw_rows']:.0f} /
  {diagnostics['normalized_rows']:.0f}，榜单展示重复占比：
  {diagnostics['deduplicated_row_share']:.2%}。
- 最新净买入强度 P1/中位/P99：{distribution['p01']:.4f} /
  {distribution['median']:.4f} / {distribution['p99']:.4f}。
- 因子与成交额/波动率/120日收益的月度 Spearman 中位：
  {correlations['amount20']:.3f} / {correlations['vol60']:.3f} /
  {correlations['ret120']:.3f}。
- 事件键重复/净买入恒等式异常/未来可见性异常：
  {diagnostics['duplicate_event_keys']:.0f} /
  {diagnostics['net_buy_identity_violations']:.0f} /
  {diagnostics['visibility_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""
