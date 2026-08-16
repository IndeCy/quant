"""走步双因子残差动量数据可行性报告。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def render_report(result: Mapping[str, Any]) -> str:
    """渲染冻结数据门禁结果。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    correlations = result["median_correlations"]
    return f"""# 走步双因子残差动量数据可行性 V1

- 数据截止：{result["latest_date"]}，月末截面：
  {result["signal_months"]}。
- 估计窗：信号日前252至121个交易日；评价窗：120至20个交易日。
- 风格因子：沪深300收益、中证500相对沪深300收益。
- 本阶段不读取未来收益、不执行回测、不选择参数。

## 数据与区分度

- 候选数最少/中位/最新：
  {result["candidate_count_min"]} /
  {result["candidate_count_median"]:.0f} /
  {result["candidate_count_latest"]}。
- 因子唯一值中位数：
  {result["unique_values_median"]:.0f}。
- Top40日均成交额中位数：
  {result["top40_adv_median_rmb"]:,.0f}元。
- 合格月份占比：
  {result["qualified_month_share"]:.1%}。
- 与普通12-1动量/60日波动/120日收益秩相关中位数：
  {correlations["intermediate_momentum"]:.3f} /
  {correlations["vol60"]:.3f} /
  {correlations["ret120"]:.3f}。
- 最小估计窗/评价窗观测：
  {result["minimum_estimation_observations"]} /
  {result["minimum_evaluation_observations"]}。
- 最大恒等式误差：
  {result["maximum_identity_error"]:.3e}。

## 冻结门禁

{checks}

## 结论

- 决策：`{result["decision"]}`。
- 未通过时禁止进入收益回测；通过只代表允许执行一次固定多折研究。
"""
