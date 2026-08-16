"""真实大单资金流数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """生成数据覆盖、金额一致性和机制独立性报告。"""
    diagnostics = result["diagnostics"]
    distribution = result["latest_distribution"]
    correlations = result["median_correlations"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 真实大单资金流数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 合格月份（全样本/2025年至今）：{result['qualified_month_share']:.2%} /
  {result['locked_qualified_month_share']:.2%}。
- 正大单流候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}。
- 交易日同步成功/空结果占比：{diagnostics['successful_trade_day_share']:.2%} /
  {diagnostics['empty_trade_day_share']:.2%}；单日最多原始行：
  {diagnostics['max_raw_rows']:.0f}。
- 全订单净额与源净流入恒等式异常占比：
  {diagnostics['net_identity_violation_share']:.2%}。
- 分类金额/行情成交额 P1/中位/P99：
  {diagnostics['turnover_ratio_p01']:.3f} /
  {diagnostics['turnover_ratio_median']:.3f} /
  {diagnostics['turnover_ratio_p99']:.3f}。
- 最新大单净流入占比 P1/中位/P99：{distribution['p01']:.4f} /
  {distribution['median']:.4f} / {distribution['p99']:.4f}。
- 与成交额/波动率/20日收益/120日收益/旧成交额压力的Spearman中位：
  {correlations['amount20']:.3f} / {correlations['vol60']:.3f} /
  {correlations['ret20']:.3f} / {correlations['ret120']:.3f} /
  {correlations['signed_amount_pressure']:.3f}。
- 缓存重复/未来可见性/因子范围异常：
  {diagnostics['duplicate_daily_rows']:.0f} /
  {diagnostics['visibility_violations']:.0f} /
  {diagnostics['factor_range_violations']:.0f}。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""
