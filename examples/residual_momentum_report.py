"""走步双因子残差动量固定多折研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(
    result: dict[str, Any],
) -> str:
    """渲染业绩、持仓暴露和样本外风格残差。"""
    metrics = result["period_metrics"]
    annual = result["annual_metrics"]
    gate = result["gate"]
    style = result["style_residual"]
    diagnostics = result["diagnostics"]
    risk = result["risk_summary"]
    counts = result["candidate_counts"]
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
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['excess_return']:.2%} |"
        for year, item in annual.items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    failed_style = ", ".join(style["failed_checks"]) or "无"
    return f"""# 走步双因子残差动量 V1

- 数据截止：{result["latest_date"]}。
- 因子：用信号日前252至121日估计市场和中盘Beta，再累计
  120至20日的个股残差收益；最近20日不参与信号。
- 组合：标准全A股票池、Top40月频等权。
- 执行：M0 T+1、qfq、5bps滑点。
- 风险层：20日组合波动率超过45%时仓位30%，否则100%。
- 月度候选最少/中位/最新：{counts["min"]:.0f} /
  {counts["median"]:.0f} / {counts["latest"]:.0f}。
- 与 Quality 日收益相关性：
  {result["quality_return_correlation"]:.3f}。
- 入选残差动量/市场Beta/中盘Beta/60日波动中位：
  {diagnostics["selected_residual_momentum_median"]:.2%} /
  {diagnostics["selected_market_beta_median"]:.2f} /
  {diagnostics["selected_size_beta_median"]:.2f} /
  {diagnostics["selected_vol60_median"]:.2%}。
- 入选日均成交额中位：
  {diagnostics["selected_adv_median_rmb"] / 1_000_000:.1f}百万元。
- 平均仓位/降仓交易日/风险切换次数：
  {risk["average_exposure"]:.1%} /
  {risk["reduced_days"]:.0f} /
  {risk["event_count"]:.0f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 | 成本影响 |
|---|---:|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe | 超额收益 |
|---:|---:|---:|---:|---:|
{annual_rows}

## 中盘风格走步残差

- 验证期Beta/平均残差：
  {style["validation_beta"]:.3f} /
  {style["validation_mean_residual"]:.2%}。
- 锁定期Beta/平均残差/正残差年份/残差IR/最差年：
  {style["locked_beta"]:.3f} /
  {style["locked_mean_residual"]:.2%} /
  {style["locked_positive_year_share"]:.1%} /
  {style["locked_residual_information_ratio"]:.3f} /
  {style["locked_worst_residual"]:.2%}。
- 风格残差失败项：{failed_style}。

## 冻结晋级门槛

{checks}

结论：{'允许进入独立前瞻确认，不直接注册生产' if gate['passed'] else '终止，不注册生产策略'}。
"""
