"""Amihud 非流动性固定研究报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    diagnostics: dict[str, float],
    candidate_counts: dict[str, float],
    latest_date: str,
) -> str:
    """生成四折结果、可交易性与暴露归因报告。"""
    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in metrics.items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in annual.items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    return f"""# Amihud 非流动性溢价 V1

- 数据截止：{latest_date}；因子为60日平均绝对收益除以人民币成交额。
- 组合与执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 月度候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与20日成交额/60日波动/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_amount20']:.3f} /
  {diagnostics['median_spearman_with_vol60']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与低成交额/高波动/120日动量 Top40 重合中位数：
  {diagnostics['median_top40_overlap_with_low_amount']:.1%} /
  {diagnostics['median_top40_overlap_with_high_vol60']:.1%} /
  {diagnostics['median_top40_overlap_with_ret120']:.1%}。
- 入选日均成交额中位/P1：
  {diagnostics['selected_adv_median_rmb'] / 1e6:.1f} /
  {diagnostics['selected_adv_p01_rmb'] / 1e6:.1f} 百万元。
- 500万元、40只等权在中位成交额上的单次参与率：
  {diagnostics['reference_capital_participation']:.2%}。
- 入选单日冲击集中度中位数：
  {diagnostics['selected_impact_concentration_median']:.2%}；
  截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""
