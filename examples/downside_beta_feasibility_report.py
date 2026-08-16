"""低下行 Beta 可行性报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """生成数据、语义排重与成交能力报告。"""
    distribution = result["latest_distribution"]
    diagnostics = result["diagnostics"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 低下行 Beta 数据与排重可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 252日窗口至少200个总样本、60个沪深300下跌日；越低越防御。
- 候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 唯一因子值最少：{result['unique_value_min']}。
- Top40月度日均成交额中位数最低值：
  {result['minimum_top40_median_adv_rmb'] / 1e6:.1f}百万元；
  高于500万元的持仓比例最低值：
  {result['minimum_top40_tradable_share']:.1%}。
- 最新下行 Beta P1/中位/P99：
  {distribution['downside_p01']:.3f} /
  {distribution['downside_median']:.3f} /
  {distribution['downside_p99']:.3f}。
- 最新总 Beta / 上行 Beta 中位数：
  {distribution['total_beta_median']:.3f} /
  {distribution['upside_beta_median']:.3f}。
- 与低总Beta/低60日波动 Spearman 中位数：
  {diagnostics['median_spearman_with_low_total_beta']:.3f} /
  {diagnostics['median_spearman_with_low_vol60']:.3f}；
  Top40重合：
  {diagnostics['median_top40_overlap_with_low_total_beta']:.1%} /
  {diagnostics['median_top40_overlap_with_low_vol60']:.1%}。
- 与成交额/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_amount20']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 重复主键/窗口异常：
  {diagnostics['duplicate_signal_symbol_rows']:.0f} /
  {diagnostics['observation_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段没有运行收益回测，也没有注册生产策略。
"""
