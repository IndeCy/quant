"""标普500与黄金12%波动目标机会成本报告。"""

from __future__ import annotations

from typing import Any


NAMES = {
    "sp500_gold_60_40_vol_target_12_v1": "标普/黄金60/40块 12%波动目标",
    "sp500_direct_vol_target_12_control": "标普500 12%波动目标简单对照",
    "sp500_direct_control_for_vol_target": "直接持有标普500ETF",
    "sp500_gold_60_40_vol_target_12_cost_20bps": "候选20bps压力",
}


def render_report(result: dict[str, Any]) -> str:
    """渲染同风险机制下的机会成本证据。"""
    period_rows: list[str] = []
    for strategy_id, periods in result["period_comparison"].items():
        for period, item in periods.items():
            period_rows.append(
                f"| {NAMES[strategy_id]} | {period} | "
                f"{item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['annual_turnover']:.2f}x |"
            )
    annual_rows = "\n".join(
        f"| {year} | {candidate['annualized_return']:.2%} | "
        f"{result['annual_comparison']['sp500_direct_vol_target_12_control'][year]['annualized_return']:.2%} | "
        f"{result['annual_comparison']['sp500_direct_control_for_vol_target'][year]['annualized_return']:.2%} |"
        for year, candidate in result["annual_comparison"][
            "sp500_gold_60_40_vol_target_12_v1"
        ].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    diagnostics = result["diagnostics"]
    decision = (
        "通过同机制机会成本门槛，仅允许进入前向Paper观察"
        if result["gate"]["passed"]
        else "未通过同机制机会成本门槛，归档且不注册"
    )
    return f"""# 标普500 × 黄金60/40块 12%波动目标 V1

- 候选风险块固定60% 513500.SH、40% 518880.SH。
- 对照风险块为100% 513500.SH。
- 两者使用完全相同的12%年化波动目标、63交易日回看和月频调整。
- 风险块不加杠杆；未使用的预算进入511010.SH。
- 月末信号、下一交易日成交；统一qfq、M0 T+1、5bps。
- 正式评价从2019-01-01开始，2022-01-01后为锁定检验。

| 组合 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

## 年度表现

| 年份 | 候选 | 同机制标普对照 | 直接513500 |
|---:|---:|---:|---:|
{annual_rows}

## 风险匹配与机会成本

- 候选评价期年化波动：{diagnostics['candidate_volatility']:.2%}。
- 同机制标普对照年化波动：{diagnostics['vol_target_control_volatility']:.2%}。
- 直接513500年化波动：{diagnostics['direct_sp500_volatility']:.2%}。
- 候选平均风险块占比：{diagnostics['candidate_average_risk_allocation']:.2%}。
- 候选最低/最高风险块占比：
  {diagnostics['candidate_min_risk_allocation']:.2%} /
  {diagnostics['candidate_max_risk_allocation']:.2%}。
- 相对同机制标普对照年化收益差：
  {result['gate']['return_lift_vs_vol_target_control']:.2%}。
- 相对直接513500年化收益差：
  {result['gate']['return_lift_vs_direct_sp500']:.2%}。
- 最差单日：{diagnostics['worst_day']:.2%}。
- 95% Expected Shortfall：{diagnostics['expected_shortfall_95']:.2%}。
- 最长水下期：{diagnostics['max_underwater_days']}个交易日。
- 与Quality日收益相关性：{diagnostics['quality_correlation']:.3f}。

## 冻结门槛

{checks}

## 结论

{decision}。本研究不自动注册、不接入scheduler、Paper或实盘。
"""
