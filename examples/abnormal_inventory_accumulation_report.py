"""异常存货积累研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """根据数据门禁结果渲染可行性或完整回测报告。"""
    data_gate = result["data_gate"]
    monthly = result["candidate_counts"]
    data_checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in data_gate["checks"].items()
    )
    header = f"""# 异常存货积累因子 V1

- 数据截止：{result['latest_date']}。
- 因子：`ln(存货同比倍数)-ln(营收同比倍数)`，越低越好。
- 财务口径：一般工商业、连续两年1231年报、逐报表 `f_ann_date` as-of。
- 股票池：上市满3年，剔除ST/退市/停牌/成交额最低20%。
- 组合与执行：Top40月频等权，qfq、M0 T+1、5bps及固定风险层。
- 可投股票数最少：{data_gate['investable_count_min']:.0f}。
- 有效候选最少/中位/最新：{monthly['min']:.0f} /
  {monthly['median']:.0f} / {monthly['latest']:.0f}。
- 有效覆盖率最少/中位：{data_gate['coverage_min']:.1%} /
  {data_gate['coverage_median']:.1%}。

## 数据门禁

{data_checks}
"""
    if result["decision"] == "REJECTED_BEFORE_BACKTEST":
        return (
            header
            + "\n结论：数据门禁未通过，未读取未来收益、未启动回测、"
            "不注册生产策略。\n"
        )
    metrics = result["period_metrics"]
    annual = result["annual_metrics"]
    diagnostics = result["diagnostics"]
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
    gate_checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    return header + f"""
## 因子归因

- 与纯存货增长/营收增长/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_inventory_growth']:.3f} /
  {diagnostics['median_spearman_with_revenue_growth']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与纯低存货增长/高动量 Top40 重合中位数：
  {diagnostics['median_top40_overlap_with_low_inventory_growth']:.1%} /
  {diagnostics['median_top40_overlap_with_momentum']:.1%}。
- 最高分并列数中位/最大：
  {diagnostics['median_top_score_tie_count']:.0f} /
  {diagnostics['maximum_top_score_tie_count']:.0f}；
  Top40 落在缩尾并列区的中位占比：
  {diagnostics['median_selected_clipped_tie_share']:.1%}。
- 入选异常积累/存货增长/营收增长中位数：
  {diagnostics['selected_abnormal_accumulation_median']:.3f} /
  {diagnostics['selected_inventory_log_growth_median']:.3f} /
  {diagnostics['selected_revenue_log_growth_median']:.3f}。
- 与 Quality Balanced Value 日收益相关性：
  {result['quality_return_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{gate_checks}

结论：{'通过研究门槛，仅允许进入独立确认' if result['gate']['passed'] else '未通过固定门槛，终止且不注册生产策略'}。
"""
