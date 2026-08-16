"""低收益偏度研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染数据审计、归因与固定样本外结果。"""
    if result["decision"] == "REJECTED_BEFORE_BACKTEST":
        checks = "\n".join(
            f"- {'PASS' if passed else 'FAIL'}：{name}"
            for name, passed in result["data_gate"]["checks"].items()
        )
        return f"""# 低60日收益偏度 V1

- 数据截止：{result['latest_date']}。
- 因子：过去60个交易日日收益样本偏度，越低越好，不缩尾。
- 数据覆盖最低/中位：{result['data_gate']['coverage_min']:.1%} /
  {result['data_gate']['coverage_median']:.1%}。

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
    execution_rows = "\n".join(
        f"| {period} | {item['net_annualized_return']:.2%} | "
        f"{item['frictionless_annualized_return']:.2%} | "
        f"{item['annualized_return_drag']:.2%} | "
        f"{item['net_sharpe']:.3f} | "
        f"{item['frictionless_sharpe']:.3f} |"
        for period, item in result["execution_attribution"].items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    diagnostics = result["diagnostics"]
    execution_diagnosis = result["execution_diagnosis"]
    counts = result["candidate_counts"]
    execution_conclusion = (
        "零摩擦核心门槛通过，净收益失败主要属于执行负Alpha。"
        if execution_diagnosis["frictionless_passed_core_gate"]
        else "零摩擦核心门槛仍未通过，属于毛信号偏弱且交易摩擦继续拖累。"
    )
    return f"""# 低60日收益偏度 V1

- 数据截止：{result['latest_date']}。
- 因子：过去60个交易日日收益样本偏度，越低越好，不缩尾。
- 可见性：T日收盘只使用T日及以前60个有效收益，T+1成交。
- 股票池：上市满3年，剔除ST/退市/停牌/成交额最低20%。
- 组合与执行：Top40月频等权，qfq、M0、5bps及固定风险层。
- 候选数最少/中位/最新：{counts['min']:.0f} /
  {counts['median']:.0f} / {counts['latest']:.0f}。
- 与60日波动/MAX20/120日动量 Spearman 中位数：
  {diagnostics['median_spearman_with_vol60']:.3f} /
  {diagnostics['median_spearman_with_max20']:.3f} /
  {diagnostics['median_spearman_with_ret120']:.3f}。
- 与低波/低MAX Top40重合中位数：
  {diagnostics['median_top40_overlap_with_lowvol']:.1%} /
  {diagnostics['median_top40_overlap_with_lowmax']:.1%}。
- 入选偏度/波动/MAX20中位数：
  {diagnostics['selected_skewness_median']:.3f} /
  {diagnostics['selected_vol60_median']:.3f} /
  {diagnostics['selected_max20_median']:.3f}。
- 截止位最大并列：{diagnostics['maximum_cutoff_tie_count']:.0f}。
- 与 Quality Balanced Value 日收益相关性：
  {result['quality_return_correlation']:.3f}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---:|---:|---:|---:|---:|---:|
{period_rows}

## 执行摩擦归因

零摩擦反事实保留相同股票池、信号、月频调仓、风险层、T+1及不可成交约束，
仅将佣金、印花税和滑点设为零。

| 区间 | 净年化 | 零摩擦年化 | 年化收益拖累 | 净Sharpe | 零摩擦Sharpe |
|---|---:|---:|---:|---:|---:|
{execution_rows}

归因结论：{execution_conclusion}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 固定晋级门槛

{checks}

结论：{'通过研究门槛，仅允许进入独立确认' if result['gate']['passed'] else '未通过固定门槛，终止且不注册生产策略'}。
"""
