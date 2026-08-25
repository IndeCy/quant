"""Quality Balanced Value 低效窗口归因报告渲染。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """把固定因子腿实验结果渲染成可复核 Markdown。"""
    windows = list(result["diagnostic_windows"])
    metric_rows = _metric_rows(result["period_metrics"], windows)
    effect_rows = _effect_rows(result["leave_one_out"], windows)
    overlap_rows = _overlap_rows(result["holding_diagnostics"], windows)
    exposure_rows = _exposure_rows(result["holding_diagnostics"], windows)
    diagnosis = result["diagnosis"]
    audit = result["corporate_action_audit"]
    return f"""# Quality Balanced Value 低 Sharpe 窗口归因

- 数据截止：{result["latest_date"]}
- 诊断窗口：{", ".join(windows)}
- 固定口径：同一股票池、Top20月频、qfq、M0 T+1、5bps、GRID风险层。
- 因子腿：Quality=ROE/ROA/OCF等权，E/P与B/P沿用原策略1%/99%缩尾。
- 原策略权重：Quality 80%、E/P 10%、B/P 10%；子组合仅按原权重相对比例归一。
- 公司行动门禁：检查{audit["checked_rows"]}条，剔除{audit["excluded_rows"]}条重大复权变化。
- 本研究只做归因，不选参数、不改变生产策略。

## 窗口表现

| 因子腿 | 窗口 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额收益 |
|---|---|---:|---:|---:|---:|---:|
{metric_rows}

## 删除法边际贡献

正的回撤变化表示回撤变浅；其余正值表示加入该因子腿后指标提高。

| 作用 | 窗口 | 年化收益变化 | 回撤变化 | Sharpe变化 | Calmar变化 | 超额变化 |
|---|---|---:|---:|---:|---:|---:|
{effect_rows}

## 持仓重叠

| 因子腿 | 窗口 | 与原策略月度持仓重叠中位数 |
|---|---|---:|
{overlap_rows}

## 持仓暴露

| 因子腿 | 窗口 | ROA中位数 | E/P中位数 | B/P中位数 | 60日波动率中位数 | 20日成交额中位数(亿元) |
|---|---|---:|---:|---:|---:|---:|
{exposure_rows}

## 诊断

- 归因标签：`{diagnosis["label"]}`
- 解释：{diagnosis["explanation"]}
- 纯Quality窗口中位Sharpe：{diagnosis["median_sharpes"]["quality_only"]:.3f}
- 纯E/P窗口中位Sharpe：{diagnosis["median_sharpes"]["earnings_yield_only"]:.3f}
- 纯B/P窗口中位Sharpe：{diagnosis["median_sharpes"]["book_yield_only"]:.3f}
- 原策略窗口中位Sharpe：{diagnosis["median_sharpes"]["balanced"]:.3f}
- 估值扩展对Quality的窗口中位Sharpe边际：{diagnosis["median_value_extension_sharpe_effect"]:+.3f}
- Quality对纯估值的窗口中位Sharpe边际：{diagnosis["median_quality_conditional_sharpe_effect"]:+.3f}

结论：该结果用于解释既有低效窗口，不构成删因子、改权重或策略晋级依据。
"""


def _metric_rows(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    windows: Sequence[str],
) -> str:
    rows: list[str] = []
    for variant, periods in metrics.items():
        for window in windows:
            item = periods[window]
            rows.append(
                f"| {variant} | {window} | {item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
                f"{item['calmar']:.3f} | {item['excess_return']:.2%} |"
            )
    return "\n".join(rows)


def _effect_rows(
    leave_one_out: Mapping[str, Any],
    windows: Sequence[str],
) -> str:
    rows: list[str] = []
    for window in windows:
        for effect, item in leave_one_out["by_window"][window].items():
            rows.append(
                f"| {effect} | {window} | {item['annualized_return']:+.2%} | "
                f"{item['max_drawdown']:+.2%} | {item['sharpe']:+.3f} | "
                f"{item['calmar']:+.3f} | {item['excess_return']:+.2%} |"
            )
    return "\n".join(rows)


def _overlap_rows(
    diagnostics: Mapping[str, Any],
    windows: Sequence[str],
) -> str:
    return "\n".join(
        f"| {variant} | {window} | {value:.2%} |"
        for variant, periods in diagnostics["overlap_with_balanced"].items()
        for window, value in periods.items()
        if window in windows
    )


def _exposure_rows(
    diagnostics: Mapping[str, Any],
    windows: Sequence[str],
) -> str:
    rows: list[str] = []
    for variant, periods in diagnostics["feature_medians"].items():
        for window, item in periods.items():
            if window not in windows:
                continue
            rows.append(
                f"| {variant} | {window} | {item['roa']:.4f} | "
                f"{item['earnings_yield']:.4f} | {item['book_yield']:.4f} | "
                f"{item['vol60']:.2%} | {item['amount20_yi']:.2f} |"
            )
    return "\n".join(rows)
