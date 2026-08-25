"""官方源净流入数据可行性报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染覆盖、源字段契约和独立性结论。"""
    diagnostics = result["diagnostics"]
    correlations = result["median_correlations"]
    distribution = result["latest_distribution"]
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["checks"].items()
    )
    return f"""# 官方源净流入数据可行性 V1

- 数据截止：{result['latest_date']}，月末截面 {result['signal_months']} 个。
- 合格月份（全样本/2025年至今）：{result['qualified_month_share']:.2%} /
  {result['locked_qualified_month_share']:.2%}。
- 正净流入候选最少/中位/最新：{result['candidate_count_min']} /
  {result['candidate_count_median']:.0f} / {result['candidate_count_latest']}。
- 因子唯一值中位数：{result['unique_values_median']:.0f}。
- 交易日同步成功率/单日最多行：
  {diagnostics['successful_trade_day_share']:.2%} /
  {diagnostics['max_raw_rows']:.0f}。
- 全档买卖差近零占比：{diagnostics['symmetric_bucket_share']:.2%}。
- 分类金额/行情成交额 P1/中位/P99：
  {diagnostics['turnover_ratio_p01']:.3f} /
  {diagnostics['turnover_ratio_median']:.3f} /
  {diagnostics['turnover_ratio_p99']:.3f}。
- 最新源净流入占比 P1/中位/P99：{distribution['p01']:.4f} /
  {distribution['median']:.4f} / {distribution['p99']:.4f}。
- 与成交额/波动率/20日收益/120日收益/旧成交额压力的Spearman中位：
  {correlations['amount20']:.3f} / {correlations['vol60']:.3f} /
  {correlations['ret20']:.3f} / {correlations['ret120']:.3f} /
  {correlations['signed_amount_pressure']:.3f}。
- 重复/未来可见性/源净流入范围异常：
  {diagnostics['duplicate_daily_rows']:.0f} /
  {diagnostics['visibility_violations']:.0f} /
  {diagnostics['source_share_range_violations']:.0f}。

## 说明

`net_mf_amount` 是数据商给出的净流入字段，内部主动买卖判定方法不透明。
本研究只验证它是否稳定、独立且可回测，不把它解释为可直接观察的真实机构买卖。

## 冻结门槛

{checks}

## 结论

{result['decision']}。本阶段未运行收益回测，也未注册生产策略。
"""
