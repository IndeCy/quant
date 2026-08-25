"""长期反转数据可行性报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """把结构化门禁结果渲染为可读报告。"""
    correlations = result["median_correlations"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 长期反转数据可行性 V1.1

- 数据截止：{result["latest_date"]}，月末截面 {result["signal_months"]} 个。
- 合格月份占比：{result["qualified_month_share"]:.2%}。
- 候选数最少/中位/最新：{result["candidate_count_min"]} /
  {result["candidate_count_median"]:.0f} / {result["candidate_count_latest"]}。
- 因子唯一值中位数：{result["unique_values_median"]:.0f}。
- Top40 日均成交额中位数的月度中位：\
{result["top40_adv_median_rmb"] / 1_000_000:.1f} 百万元。
- 与近期120日收益/60日波动率 Spearman 中位：
  {correlations["ret120"]:.3f} / {correlations["vol60"]:.3f}。
- 收益恒等式最大误差：{result["max_identity_error"]:.3e}。
- 重复/点时违规/无效值：{result["duplicate_rows"]} /
  {result["visibility_violations"]} / {result["invalid_rows"]}。

## 冻结门槛

{checks}

## 结论

{result["decision"]}。本阶段不计算未来收益，也不注册生产策略。
"""
