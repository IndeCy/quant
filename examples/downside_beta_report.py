"""低下行 Beta 固定四折研究报告渲染。"""

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
    """生成跨阶段结果、风格归因和市场板块暴露报告。"""
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
    return f"""# 低下行 Beta 防御因子 V1

- 数据截止：{latest_date}；252日窗口只在510300下跌日估计联动Beta。
- 组合与执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 月度候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与低总Beta/低60日波动/成交额/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_low_total_beta']:.3f} /
  {diagnostics['median_spearman_with_low_vol60']:.3f} /
  {diagnostics['median_spearman_with_amount20']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与低总Beta/低60日波动 Top40 重合中位数：
  {diagnostics['median_top40_overlap_with_low_total_beta']:.1%} /
  {diagnostics['median_top40_overlap_with_low_vol60']:.1%}。
- 入选下行/总/上行Beta及60日波动中位数：
  {diagnostics['selected_downside_beta_median']:.3f} /
  {diagnostics['selected_total_beta_median']:.3f} /
  {diagnostics['selected_upside_beta_median']:.3f} /
  {diagnostics['selected_vol60_median']:.3%}。
- 最新 Top40 北交所/科创板/创业板占比：
  {diagnostics['latest_bj_share']:.1%} /
  {diagnostics['latest_star_share']:.1%} /
  {diagnostics['latest_chinext_share']:.1%}；
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
