"""独立因子多折复验的 Markdown 报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    metrics: dict[str, dict[str, dict[str, float]]],
    gates: dict[str, dict[str, Any]],
    correlations: dict[str, float],
    comparator: dict[str, Any],
    latest_date: str,
    decision: str,
) -> str:
    """渲染指标、门槛和相关性，计算事实仍来自结构化结果。"""
    metric_rows: list[str] = []
    for strategy_id, period_metrics in metrics.items():
        for period, item in period_metrics.items():
            metric_rows.append(
                f"| {strategy_id} | {period} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    gate_rows = "\n".join(
        f"| {strategy_id} | {'PASS' if gate['passed'] else 'FAIL'} | "
        f"{gate['positive_folds']}/4 | {gate['worst_fold_drawdown']:.2%} | "
        f"{gate['median_fold_sharpe']:.3f} |"
        for strategy_id, gate in gates.items()
    )
    failed_checks = "\n".join(
        f"- {strategy_id}："
        + "、".join(name for name, passed in gate["checks"].items() if not passed)
        for strategy_id, gate in gates.items()
    )
    correlation_rows = "\n".join(
        f"| {period} | {value:.3f} |"
        for period, value in correlations.items()
    )
    quality_full = comparator.get("period_metrics", {}).get("full", {})
    return f"""# 独立因子多折复验 V1

- 数据截止：{latest_date}。
- 候选在运行前固定为业绩预告确定性动量、重要股东净增持。
- 两个候选均原样复用因子、股票池、Top40、风险层和M0成交口径。
- 本研究使用过2022年后的结果做候选筛选，因此只能用于回顾性诊断。

| 候选 | 阶段 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 | 年化换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(metric_rows)}

## 固定多折门槛

| 候选 | 结论 | 正收益折 | 最差折回撤 | 折Sharpe中位数 |
|---|---|---:|---:|---:|
{gate_rows}

未通过项：

{failed_checks}

## 候选相关性

| 阶段 | 两候选日收益相关性 |
|---|---:|
{correlation_rows}

## 既有稳健策略对照

Quality Balanced Value 的全样本年化为
{float(quality_full.get('annualized_return', float('nan'))):.2%}，最大回撤
{float(quality_full.get('max_drawdown', float('nan'))):.2%}，Sharpe
{float(quality_full.get('sharpe', float('nan'))):.3f}。

## 结论

决策：`{decision}`。

即使存在通过者，也不能直接注册生产策略。候选筛选已经观察了全部历史数据，
下一份有效证据只能来自固定定义后的新前瞻Paper，不得继续在历史窗口上调参数。
"""
