"""境内纳指与黄金固定60/40相对标普500硬门槛报告。"""

from __future__ import annotations

from typing import Any


NAMES = {
    "nasdaq_gold_60_40_sp500_hurdle_v3": "纳指100/黄金 60/40",
    "sp500_bond_nasdaq_calibration_risk_control": "标普500/国债 校准同波动",
    "sp500_direct_nasdaq_hurdle_control": "直接持有标普500ETF",
    "nasdaq_direct_control": "直接持有纳指100ETF",
    "nasdaq_gold_60_40_sp500_hurdle_cost_20bps": "候选20bps压力",
}


def render_report(result: dict[str, Any]) -> str:
    """渲染直接标普硬门槛与同波动机会成本证据。"""
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
        f"{result['annual_comparison']['sp500_direct_nasdaq_hurdle_control'][year]['annualized_return']:.2%} | "
        f"{result['annual_comparison']['nasdaq_direct_control'][year]['annualized_return']:.2%} |"
        for year, candidate in result["annual_comparison"][
            result["strategy_id"]
        ].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    calibration = result["calibration"]
    diagnostics = result["diagnostics"]
    decision = (
        "通过直接标普硬门槛，仅允许前向Paper观察"
        if result["gate"]["passed"]
        else "未通过直接标普硬门槛，归档且不注册"
    )
    return f"""# 境内纳指100 × 黄金固定60/40相对标普500硬门槛 V3

- 候选：60% 广发纳斯达克100ETF（159941.SZ）、
  40% 华安黄金ETF（518880.SH）。
- 绝对机会成本：直接持有博时标普500ETF（513500.SH）。
- 另设只用2015-07-13至2018-12-31冻结的标普500/国债对照；
  候选已直接支配513500时，该对照只作诊断，不重复否决。
- 月末信号、下一交易日恢复固定权重；统一qfq、M0 T+1、5bps。
- 不做权重网格、择时或杠杆。
- 本地可靠共同截止：{result['latest_date']}；没有对之后日期补值。

## 数据与校准

| 项目 | 结果 |
|---|---:|
| 共同起始日 | {result['data_audit']['common_start']} |
| 共同截止日 | {result['data_audit']['common_end']} |
| 共同交易日 | {result['data_audit']['common_days']} |
| 候选校准期波动 | {calibration['candidate_volatility']:.2%} |
| 同波动对照513500权重 | {calibration['risk_control_sp500_weight']:.2%} |
| 同波动对照511010权重 | {calibration['risk_control_bond_weight']:.2%} |

## 同口径结果

| 组合 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

## 年度表现

| 年份 | 候选 | 直接513500 | 直接159941 |
|---:|---:|---:|---:|
{annual_rows}

## 机会成本与尾部

- 候选年化波动：{diagnostics['candidate_volatility']:.2%}。
- 直接513500年化波动：{diagnostics['direct_sp500_volatility']:.2%}。
- 直接159941年化波动：{diagnostics['direct_nasdaq_volatility']:.2%}。
- 相对直接513500年化收益差：
  {result['gate']['return_lift_vs_direct_sp500']:.2%}。
- 相对同波动简单对照年化收益差：
  {result['gate']['return_lift_vs_risk_control']:.2%}。
- 相对直接159941回撤改善：
  {result['gate']['drawdown_improvement_vs_direct_nasdaq']:.2%}。
- 最差单日：{diagnostics['worst_day']:.2%}。
- 95% Expected Shortfall：{diagnostics['expected_shortfall_95']:.2%}。
- 最长水下期：{diagnostics['max_underwater_days']}个交易日。
- 与Quality日收益相关性：{diagnostics['quality_correlation']:.3f}。

## 冻结门槛

{checks}

## 结论

{decision}。通过也只代表历史样本外证据，不自动注册、不接入scheduler、
Paper或实盘；跨境ETF折溢价已经包含在实际场内价格中。
"""
