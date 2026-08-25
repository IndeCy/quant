"""点时盈利收益率数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染 E/P 覆盖、可交易性与独立性门禁。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    correlations = result["median_correlations"]
    diagnostics = result["diagnostics"]
    distribution = result["latest_distribution"]
    return f"""# 点时盈利收益率数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']}。
- 候选数最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}；
  合格月份占比：{result['qualified_month_share']:.2%}。
- Top40 成交额中位数：{result['top40_adv_median_rmb']:,.0f} 元。
- 与 ROA/价格低波/120日收益/对数成交额的秩相关中位数：
  {correlations['roa']:.3f} / {correlations['vol60']:.3f} /
  {correlations['ret120']:.3f} / {correlations['log_adv']:.3f}。
- 最新 E/P P1/中位/P99：{distribution['p01']:.2%} /
  {distribution['median']:.2%} / {distribution['p99']:.2%}。
- 公司行为复权因子缺失/重大变化剔除：
  {diagnostics['adjustment_missing_share']:.2%} /
  {diagnostics['material_action_share']:.2%}。
- 公告越界/重复/无效值：{diagnostics['visibility_violations']:.0f} /
  {diagnostics['duplicate_rows']:.0f} / {diagnostics['invalid_rows']:.0f}。

## 冻结门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 本阶段没有读取未来收益、执行回测或调整参数。
"""
