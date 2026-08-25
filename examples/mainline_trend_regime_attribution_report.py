"""主线链动趋势状态归因报告渲染。"""

from __future__ import annotations

from typing import Any

import pandas as pd


def render_report(
    metrics: pd.DataFrame,
    episodes: pd.DataFrame,
    candidates: dict[str, Any],
    audit: dict[str, Any],
) -> str:
    """渲染状态表现、稳定性和冻结门槛。"""
    full = metrics[metrics["period"] == "full"]
    rows = "\n".join(
        "| {regime} | {days} | {share:.1%} | {sat_ret:.2%} | "
        "{sat_dd:.2%} | {sat_sharpe:.3f} | {core_ret:.2%} | "
        "{combined_ret:.2%} |".format(
            regime=row.regime,
            days=int(row.days),
            share=float(row.day_share),
            sat_ret=float(row.satellite_annualized_return),
            sat_dd=float(row.satellite_max_drawdown),
            sat_sharpe=float(row.satellite_sharpe),
            core_ret=float(row.core_annualized_return),
            combined_ret=float(row.combined_annualized_return),
        )
        for row in full.itertuples(index=False)
    )
    fold_rows = "\n".join(
        f"| {row.period} | {row.regime} | {int(row.days)} | "
        f"{row.satellite_total_return:.2%} | "
        f"{row.core_total_return:.2%} | {row.combined_total_return:.2%} |"
        for row in metrics[metrics["period"] != "full"].itertuples(
            index=False
        )
    )
    gate_rows: list[str] = []
    for regime, item in candidates.items():
        failed = [
            name
            for name, passed in item["checks"].items()
            if not passed
        ]
        gate_rows.append(
            f"| {regime} | {'PASS' if item['passed'] else 'FAIL'} | "
            f"{item['meaningful_episode_count']} | "
            f"{item['positive_episode_rate']:.1%} | "
            f"{'、'.join(failed) if failed else '-'} |"
        )
    positive = [name for name, item in candidates.items() if item["passed"]]
    decision = (
        f"状态 {', '.join(positive)} 具备另开条件式卫星研究的资格；"
        "本报告本身不改变任何生产仓位。"
        if positive
        else "没有状态通过冻结门槛，不应继续开发条件式卫星。"
    )
    return f"""# 主线链动趋势状态归因 V1

## 数据边界

- 共同区间：{audit['start_date']} 至 {audit['end_date']}，
  {audit['classified_days']} 个已分类交易日。
- 状态覆盖率：{audit['trend_regime_coverage']:.2%}。
- 完整 Beta 状态仅有 {audit['full_beta_days']} 天，未用于历史归因。
- 状态全部滞后一日：T 日收盘识别，解释 T+1 收益。

## 全样本条件表现

| 状态 | 天数 | 占比 | 卫星条件年化 | 卫星条件回撤 | 卫星Sharpe | Core条件年化 | 70/30条件年化 |
|---|---:|---:|---:|---:|---:|---:|---:|
{rows}

## 分阶段表现

| 阶段 | 状态 | 天数 | 卫星累计 | Core累计 | 70/30累计 |
|---|---|---:|---:|---:|---:|
{fold_rows}

## 连续状态段与门槛

| 状态 | 结论 | 至少5日状态段 | 正收益状态段占比 | 失败项 |
|---|---|---:|---:|---|
{chr(10).join(gate_rows)}

共识别 {len(episodes)} 个连续状态段。

## 结论

{decision}
"""
