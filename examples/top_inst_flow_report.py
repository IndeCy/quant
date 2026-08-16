"""机构席位净买入强度固定回测报告。"""

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
    """输出分段绩效、成本、风格归因和固定晋级门槛。"""
    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x | "
        f"{item['execution_cost_impact']:.2%} |"
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
    return f"""# 机构席位净买入强度 V1.1

- 数据截止：{latest_date}。
- 因子：去重后的近20交易日机构净买入 / 20日平均成交额，只保留正值。
- 组合：Top20月频等权，候选不足20只时转现金。
- 执行：qfq、M0 T+1、5bps及固定20日波动率风险层。
- 月度候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 与成交额/60日波动/120日动量 Spearman 中位：
  {diagnostics['median_spearman_with_amount20']:.3f} /
  {diagnostics['median_spearman_with_vol60']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与低成交额/高波动/高动量 Top20 重合中位：
  {diagnostics['median_overlap_low_amount']:.1%} /
  {diagnostics['median_overlap_high_vol60']:.1%} /
  {diagnostics['median_overlap_high_momentum']:.1%}。
- 入选净买入强度/事件日/平均成交额中位：
  {diagnostics['selected_flow_ratio_median']:.3f} /
  {diagnostics['selected_event_days_median']:.1f} /
  {diagnostics['selected_adv_median_rmb']:.0f} 元。
- 最新北交所/科创板/创业板占比：
  {diagnostics['latest_bj_share']:.1%} /
  {diagnostics['latest_star_share']:.1%} /
  {diagnostics['latest_chinext_share']:.1%}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 | 成本影响 |
|---|---:|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""
