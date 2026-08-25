"""多因子固定 Ridge 排序研究报告。"""

from __future__ import annotations

from typing import Any


def render_report(result: dict[str, Any]) -> str:
    """渲染样本外表现、预测诊断、系数稳定性和门槛。"""
    period_rows = "\n".join(
        f"| {period} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['calmar']:.3f} | {item['annual_turnover']:.2f}x |"
        for period, item in result["period_metrics"].items()
    )
    comparison_rows = "\n".join(
        f"| {name} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} | "
        f"{item['annual_turnover']:.2f}x |"
        for name, item in result["full_comparison"].items()
    )
    annual_rows = "\n".join(
        f"| {year} | {item['annualized_return']:.2%} | "
        f"{item['max_drawdown']:.2%} | {item['sharpe']:.3f} |"
        for year, item in result["annual_metrics"].items()
    )
    coefficient_rows = "\n".join(
        f"| {feature} | {item['mean']:.4f} | {item['positive_share']:.1%} | "
        f"{item['latest']:.4f} |"
        for feature, item in result["coefficient_stability"].items()
    )
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}：{name}"
        for name, passed in result["gate"]["checks"].items()
    )
    prediction = result["prediction_metrics"]
    attribution = result["failure_attribution"]
    return f"""# 多因子固定 Ridge Ranker V1

- 数据截止：{result['latest_date']}。
- 特征：ROA、OCF_TO_OR、E/P、B/P、60日低波。
- 模型固定为 Ridge(alpha=1)，不选择模型、不搜索参数。
- 2019年起逐年扩展 Walk Forward，训练标签退出日必须早于测试年。
- Top20等权、月频、原20日波动率风险层、qfq、M0 T+1。
- 样本外平均 RankIC：{prediction['mean_rank_ic']:.4f}；
  正IC月份：{prediction['positive_ic_ratio']:.1%}。
- 与 Quality Balanced Value 日收益相关性：
  {result['quality_return_correlation']:.3f}；
  平均持仓重叠：{result['quality_holding_overlap']:.1%}。

| 区间 | 年化收益 | 最大回撤 | Sharpe | Calmar | 年化换手 |
|---|---:|---:|---:|---:|---:|
{period_rows}

## 同口径对照

| 策略 | 年化收益 | 最大回撤 | Sharpe | 年化换手 |
|---|---:|---:|---:|---:|
{comparison_rows}

## 年度表现

| 年份 | 收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|
{annual_rows}

## 系数稳定性

| 特征 | 平均系数 | 正系数年份占比 | 最新系数 |
|---|---:|---:|---:|
{coefficient_rows}

## 失败归因

- 最高分组未来月平均收益：
  {attribution['top_bucket_forward_return']:.2%}。
- 第4至8分组平均收益：
  {attribution['middle_bucket_average_return']:.2%}。
- Top尾部相对中段收益差：
  {attribution['top_tail_return_gap']:.2%}。
- 低波因子占平均绝对系数：
  {attribution['low_vol_absolute_coefficient_share']:.1%}。
- 换手相对五因子等权：
  {attribution['turnover_multiplier_vs_equal']:.2f}倍。
- 额外执行成本影响：
  {attribution['execution_cost_gap_vs_equal']:.2%}。

## 固定门槛

{checks}

结论：{'通过严格样本外门槛，仅允许进入独立前瞻确认' if result['gate']['passed'] else '未通过固定样本外门槛，不注册策略'}。
"""
