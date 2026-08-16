"""标普500与黄金固定60/40机会成本研究报告。"""

from __future__ import annotations

from typing import Any


NAMES = {
    "sp500_gold_60_40_opportunity_cost_v1": "标普500/黄金 60/40",
    "sp500_bond_60_40_nominal_control": "标普500/国债 60/40",
    "sp500_bond_calibration_risk_matched_control": "标普500/国债 校准期同波动",
    "sp500_direct_control": "直接持有标普500ETF",
    "sp500_gold_60_40_cost_20bps": "标普500/黄金 60/40（20bps）",
}


def render_report(result: dict[str, Any]) -> str:
    """渲染机会成本、多折、尾部和成本证据。"""
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
        f"{result['annual_comparison']['sp500_direct_control'][year]['annualized_return']:.2%} | "
        f"{result['annual_comparison']['sp500_bond_calibration_risk_matched_control'][year]['annualized_return']:.2%} |"
        for year, candidate in result["annual_comparison"][
            "sp500_gold_60_40_opportunity_cost_v1"
        ].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    calibration = result["calibration"]
    diagnostics = result["diagnostics"]
    decision = (
        "通过机会成本门槛，仅允许进入前向 Paper 观察"
        if result["gate"]["passed"]
        else "未通过机会成本门槛，归档且不注册"
    )
    return f"""# 标普500 × 黄金固定60/40机会成本 V1

- 资产均为境内上交所ETF：513500.SH 与 518880.SH。
- 候选固定60%标普500ETF、40%黄金ETF，不做预测或权重网格。
- 月末信号、下一交易日恢复权重；统一qfq、M0 T+1、5bps。
- 校准期仅为2014-01-15至2018-12-31，用于冻结简单对照的风险权重。
- 正式评价期从2019-01-01开始；2022-01-01后为锁定检验。

## 校准得到的简单同波动对照

| 项目 | 结果 |
|---|---:|
| 候选校准期年化波动 | {calibration['candidate_volatility']:.2%} |
| 对照中513500权重 | {calibration['risk_control_sp500_weight']:.2%} |
| 对照中511010权重 | {calibration['risk_control_bond_weight']:.2%} |
| 对照校准期年化波动 | {calibration['risk_control_volatility']:.2%} |

## 同口径结果

| 组合 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(period_rows)}

## 年度表现

| 年份 | 候选60/40 | 直接513500 | 同波动简单对照 |
|---:|---:|---:|---:|
{annual_rows}

## 机会成本与尾部

- 候选评价期年化波动：{diagnostics['candidate_volatility']:.2%}。
- 直接513500年化波动：{diagnostics['direct_sp500_volatility']:.2%}。
- 同波动简单对照年化波动：{diagnostics['risk_control_volatility']:.2%}。
- 候选相对同波动对照年化收益差：{result['gate']['return_lift_vs_risk_control']:.2%}。
- 候选相对直接513500年化收益差：{result['gate']['return_lift_vs_direct_sp500']:.2%}。
- 候选最差单日：{diagnostics['worst_day']:.2%}。
- 候选95% Expected Shortfall：{diagnostics['expected_shortfall_95']:.2%}。
- 候选最长水下期：{diagnostics['max_underwater_days']}个交易日。
- 与Quality日收益相关性：{diagnostics['quality_correlation']:.3f}。

## 冻结门槛

{checks}

## 结论

{decision}。通过只说明候选优于本研究中预注册的简单风险匹配机会成本，
不代表未来必然跑赢，也不得自动接入scheduler、Paper或实盘。
"""
