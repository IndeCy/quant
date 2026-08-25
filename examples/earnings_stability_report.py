"""五年盈利稳定性研究报告渲染。"""

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
    """生成四折稳定性和因子污染归因报告。"""
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
    return f"""# 五年盈利稳定性 V1

- 数据截止：{latest_date}；因子为最近五个连续年报 ROA 标准差，越低越好。
- 五年平均 ROA 只排除稳定亏损，不参与评分。
- 组合与执行：Top40 月频等权，qfq、M0 T+1、5bps及固定风险层。
- 月度候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与平均ROA/当前ROA/60日低波/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_mean_roa']:.3f} /
  {diagnostics['median_spearman_with_current_roa']:.3f} /
  {diagnostics['median_spearman_with_low_vol60']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与平均ROA/60日低波/120日动量 Top40 重合中位数：
  {diagnostics['median_top40_overlap_with_mean_roa']:.1%} /
  {diagnostics['median_top40_overlap_with_low_vol60']:.1%} /
  {diagnostics['median_top40_overlap_with_ret120']:.1%}。
- 入选ROA标准差/平均ROA/60日波动中位数：
  {diagnostics['selected_roa_std_median']:.3f} /
  {diagnostics['selected_roa_mean_median']:.2f} /
  {diagnostics['selected_vol60_median']:.3%}。
- 截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}。

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
