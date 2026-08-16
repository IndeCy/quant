"""业绩预告与 Quality 确认组合的数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染双来源交集、可辨识性和流动性门禁。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 业绩预告 × Quality 确认可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']}。
- 输入：90日内正向业绩预告强度与公告日可见的 Quality 三因子。
- 组合：两项横截面百分位秩各 50%，本阶段不读取未来收益。
- 交集候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 全样本/2022年后可构造 Top40 比例：
  {result['top40_constructible_share']:.2%} /
  {result['locked_top40_constructible_share']:.2%}。
- 因子唯一值中位数：{result['unique_score_median']:.0f}。
- Top40 日均成交额中位数：
  {result['top40_adv_median_rmb'] / 1_000_000:.1f} 百万元。
- 预告分与 Quality 分月度 Spearman 中位数：
  {result['forecast_quality_correlation_median']:.3f}。
- 公告越界/重复/无效评分：
  {result['visibility_violations']} / {result['duplicate_rows']} /
  {result['invalid_rows']}。

## 冻结门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 未通过时不执行收益回测，也不注册策略。
"""
