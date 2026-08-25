"""Quality 盈利底线过滤的数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染覆盖、可构造性和实际过滤强度。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# Quality 盈利底线过滤可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']}。
- 基线：Quality 80% + E/P 10% + B/P 10%，Top20 月频等权。
- 唯一新增约束：最近五个连续年报的最低 ROA 必须大于 0。
- 本阶段不读取未来收益，不调整 Quality 权重。
- 基线候选中五年历史覆盖中位/最新：
  {result['floor_coverage_median']:.2%} /
  {result['floor_coverage_latest']:.2%}。
- 过滤后候选最少/中位/最新：
  {result['filtered_count_min']} /
  {result['filtered_count_median']:.0f} /
  {result['filtered_count_latest']}。
- 全样本/2022年后可构造 Top20：
  {result['constructible_share']:.2%} /
  {result['locked_constructible_share']:.2%}。
- 基线 Top20 被替换比例中位/最新：
  {result['replacement_share_median']:.2%} /
  {result['replacement_share_latest']:.2%}。
- 公告越界/重复：
  {result['visibility_violations']} / {result['duplicate_rows']}。

## 冻结门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 未通过时不执行收益回测，也不创建策略配置。
"""
