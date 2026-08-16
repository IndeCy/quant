"""标准化意外盈利策略报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, float]],
    annual: dict[str, dict[str, float]],
    gate: dict[str, Any],
    quality_correlation: float,
    diagnostics: dict[str, float],
    latest_date: str,
    *,
    title: str = "标准化意外盈利策略 V1",
    transform_description: str = "1%/99%缩尾后百分位排名",
) -> str:
    """输出分段绩效、独立性和固定晋级门槛。"""
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
    return f"""# {title}

- 数据截止：{latest_date}。
- 因子：季度EPS同比变化 / 当前公告前8次同比变化标准差。
- 排名：{transform_description}。
- 过滤：当前EPS为正、意外盈利为正、公告后90天内。
- 调仓：有效候选不少于20只时Top20等权，否则沿用原持仓。
- 执行：qfq、M0 T+1、5bps及固定20日波动率风险层。
- 与 Quality Balanced Value 日收益相关性：
  {quality_correlation:.3f}。
- 与120日动量截面Spearman中位数：
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与动量Top20重叠中位数：
  {diagnostics['median_top20_overlap_with_momentum']:.1%}。
- 实际重选月份：{diagnostics['rebalance_months']:.0f}；
  沿用持仓月份：{diagnostics['carried_months']:.0f}。

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
