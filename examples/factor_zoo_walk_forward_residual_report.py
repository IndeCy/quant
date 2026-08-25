"""因子动物园走步风格残差报告。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """渲染样本外风格中性诊断结果。"""
    summary = result["summary"]
    return f"""# 因子动物园走步中盘残差审计 V1

- 数据截止：{result["as_of_date"]}。
- 验证期Beta训练：2015–2018；验证：2019–2021。
- 锁定期Beta训练：2015–2021；锁定：2022–2026。
- 残差只扣除训练期估计的中证500相对沪深300斜率，保留截距作为候选Alpha。
- 本审计已经使用既有历史结果做元诊断，不具备生产晋级效力。

## 总体结果

- 完整候选：{int(summary["candidate_count"])} 个。
- 验证期平均残差为正：
  {int(summary["validation_positive_count"])} 个。
- 锁定期平均残差为正：
  {int(summary["locked_positive_count"])} 个。
- 两段平均残差同时为正：
  {int(summary["both_period_positive_count"])} 个。
- 五项门槛全部通过：
  {int(summary["gate_pass_count"])} 个。
- 候选中位验证/锁定残差：
  {summary["median_validation_residual"]:.2%} /
  {summary["median_locked_residual"]:.2%}。

## 最接近门槛的候选

| 实验 | 通过项 | 验证Beta | 锁定Beta | 验证残差 | 锁定残差 | 锁定正收益年 | 锁定IR | 最差锁定年 | 失败项 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
{_candidate_rows(result["candidate_rows"][:15])}

## 判定

- 结论：`{result["decision"]}`。
- {result["explanation"]}
- `earnings_surprise_event_v1` 的锁定残差较强，但验证期残差为负。
- `earnings_surprise_event_rank_v2` 两段残差均为正，但锁定期残差信息比率不足。
- 后续不能从这30个失败定义里继续挑历史最好者；有效证据只能来自全新定义的多折研究，
  或冻结后的前瞻Paper。
"""


def _candidate_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"| {item['experiment_id']} | {item['gate_pass_count']}/5 | "
        f"{item['validation_beta']:.2f} | {item['locked_beta']:.2f} | "
        f"{item['validation_mean_residual']:.2%} | "
        f"{item['locked_mean_residual']:.2%} | "
        f"{item['locked_positive_year_share']:.0%} | "
        f"{item['locked_residual_information_ratio']:.3f} | "
        f"{item['locked_worst_residual']:.2%} | "
        f"{', '.join(item['failed_checks']) or '无'} |"
        for item in rows
    )
