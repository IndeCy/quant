"""经营现金流稳定性固定四折研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    diagnostics: dict[str, float],
    risk_summary: dict[str, float],
    candidate_counts: dict[str, float],
    latest_date: str,
) -> str:
    """渲染冻结口径的收益、风险和因子诊断。"""
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
    return f"""# 经营现金流稳定性 V1

- 数据截止：{latest_date}。
- 因子：最近五个连续已披露年报的 `经营现金流/平均总资产` 波动，
  五年中位现金流为正后，波动越低越优。
- 组合：一般工商业标准股票池、Top40月频等权。
- 执行：M0 T+1、qfq、5bps滑点；风险层为
  `GRID(20日组合波动率>45%时仓位30%，否则100%)`。
- 月度候选最少/中位/最新：{candidate_counts['min']:.0f} /
  {candidate_counts['median']:.0f} / {candidate_counts['latest']:.0f}。
- 与 Quality 日收益相关性：{quality_correlation:.3f}。
- 入选 OCF波动/OCF中位/ROA波动/60日价格波动/日均成交额中位：
  {diagnostics['selected_ocf_std_median']:.2%} /
  {diagnostics['selected_ocf_level_median']:.2%} /
  {diagnostics['selected_roa_std_median']:.2f} /
  {diagnostics['selected_vol60_median']:.2%} /
  {diagnostics['selected_adv_median_rmb'] / 1_000_000:.1f} 百万元。
- 平均仓位/降仓交易日/风险切换次数：
  {risk_summary['average_exposure']:.1%} /
  {risk_summary['reduced_days']:.0f} /
  {risk_summary['event_count']:.0f}。
- 截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 | 成本影响 |
|---|---:|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'进入独立前瞻确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""
