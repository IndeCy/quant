"""主线链动条件式卫星组合报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    period_metrics: dict[str, dict[str, dict[str, float]]],
    gate: dict[str, Any],
    audit: dict[str, Any],
    active_share: float,
    transition_count: int,
) -> str:
    """输出三种组合对照和冻结门槛。"""
    rows: list[str] = []
    for period, variants in period_metrics.items():
        for variant, item in variants.items():
            rows.append(
                f"| {period} | {variant} | "
                f"{item['annualized_return']:.2%} | "
                f"{item['max_drawdown']:.2%} | "
                f"{item['sharpe']:.3f} | {item['calmar']:.3f} | "
                f"{item['excess_return']:.2%} | "
                f"{item['annual_turnover']:.2f}x |"
            )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in gate["checks"].items()
    )
    decision = (
        "历史门槛通过，但状态来自同一历史样本，只能冻结后进入前向观察，"
        "不得注册生产策略。"
        if gate["passed"]
        else "历史门槛未通过，停止该条件式卫星方向。"
    )
    return f"""# 主线链动 RISK_POSITIVE 条件式卫星 V1

## 固定定义

- 状态：前一交易日 `MA60 < MA120` 且上证20日收益为正。
- 状态满足时：Quality Core 70% + 主线链动30%。
- 其他时间：Quality Core 100%。
- 状态在 T 日收盘可见，T+1 切换；调拨成本10bps。
- 共同区间：{audit['start_date']} 至 {audit['end_date']}。
- 卫星启用交易日占比：{active_share:.2%}，发生 {transition_count} 次切换。

## 组合对照

| 阶段 | 组合 | 年化收益 | 最大回撤 | Sharpe | Calmar | 超额 | 调拨换手 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## 冻结门槛

{checks}

## 重要限制

`RISK_POSITIVE` 来自同一段历史的先验归因，本实验不是独立样本外验证。
通过历史门槛只代表值得前向观察，不代表可生产晋级。

## 结论

{decision}
"""
