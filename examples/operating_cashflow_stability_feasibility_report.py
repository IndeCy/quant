"""经营现金流稳定性数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染覆盖、可交易性和独立性门禁。"""
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    correlations = result["median_correlations"]
    distribution = result["latest_distribution"]
    return f"""# 经营现金流稳定性数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面：{result['signal_months']}。
- 候选数最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}；
  合格月份占比：{result['qualified_month_share']:.2%}。
- Top40 成交额中位数：{result['top40_adv_median_rmb']:,.0f} 元。
- 与 ROA稳定性/价格低波/120日收益/对数成交额的秩相关中位数：
  {correlations['roa_stability']:.3f} /
  {correlations['vol60']:.3f} /
  {correlations['ret120']:.3f} /
  {correlations['log_adv']:.3f}。
- 最新截面 OCF波动 P1/中位/P99：{distribution['std_p01']:.2%} /
  {distribution['std_median']:.2%} / {distribution['std_p99']:.2%}；
  五年 OCF/资产中位数：{distribution['ocf_median']:.2%}。
- 重复/公告越界/窗口长度错误：{result['duplicate_rows']} /
  {result['visibility_violations']} / {result['window_violations']}。

## 冻结门禁

{checks}

## 结论

- 决策：`{result['decision']}`。
- 本阶段没有读取未来收益、执行回测或调整参数。
"""
