"""核心利润纯度研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染点时数据门禁、多折回测和独立性结论。"""
    if result["decision"] == "REJECTED_BEFORE_BACKTEST":
        checks = _checks(result["data_gate"]["checks"])
        return f"""# 核心利润纯度 V1

- 数据截止：{result['latest_date']}。
- 因子：盈利公司扣非利润占净利润比例，越高越好。
- 财务可见性：仅使用信号日已披露的1231年报，报告年龄1至2年。
- 月度合格截面比例：{result['data_gate']['qualified_month_share']:.1%}。
- 候选数最少/中位/最新：
  {result['data_gate']['candidate_count_min']} /
  {result['data_gate']['candidate_count_median']:.0f} /
  {result['data_gate']['candidate_count_latest']}。

## 数据门禁

{checks}

结论：数据门禁未通过，未启动收益回测且不注册生产策略。
"""

    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
        f"{item['annual_turnover']:.2f}x |"
        for period, item in result["period_metrics"].items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    diagnostics = result["diagnostics"]
    data_gate = result["data_gate"]
    return f"""# 核心利润纯度 V1

- 数据截止：{result['latest_date']}。
- 因子：ROA为正的公司中，`dtprofit_to_profit` 越高越好。
- 处理：每月1%/99%缩尾后百分位排名，不搜索窗口或TopN。
- 可见性：仅使用信号日已披露的1231年报，报告年龄1至2年。
- 股票池：上市满3年，剔除ST、退市、停牌和成交额最低20%。
- 组合与执行：Top40月频等权、qfq、M0 T+1、5bps、GRID风险层。
- 候选数最少/中位/最新：
  {data_gate['candidate_count_min']} /
  {data_gate['candidate_count_median']:.0f} /
  {data_gate['candidate_count_latest']}。
- 因子与ROA/OCF_TO_OR/回款率/120日动量相关中位数：
  {diagnostics['median_spearman_with_roa']:.3f} /
  {diagnostics['median_spearman_with_ocf_to_or']:.3f} /
  {diagnostics['median_spearman_with_salescash_to_or']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与 Quality Balanced Value 日收益相关性：
  {result['quality_return_correlation']:.3f}。
- 入选因子中位数：{diagnostics['selected_factor_median']:.3f}；
  截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}。
- 入选比例高于100%/200%的占比：
  {diagnostics['selected_factor_above_100_share']:.1%} /
  {diagnostics['selected_factor_above_200_share']:.1%}；
  入选ROA中位数/低于1%的占比：
  {diagnostics['selected_roa_median']:.2f}% /
  {diagnostics['selected_roa_below_1_share']:.1%}。
- 缩尾后每月最高分最大并列：
  {diagnostics['maximum_top_score_tie_count']:.0f}只。
- 语义审计：当前高值方向实际选择“扣非利润显著高于报表净利润”的公司，
  更接近非经常项目负拖累暴露，不等同于利润结构接近100%的中性纯度。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定多折晋级门槛

{_checks(result['gate']['checks'])}

结论：{'仅进入独立确认，不直接注册生产' if result['gate']['passed'] else '未通过固定多折门槛，终止且不注册生产策略'}。
"""


def _checks(checks: dict[str, bool]) -> str:
    """格式化门禁结果。"""
    return "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in checks.items()
    )
