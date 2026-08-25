"""跨因子研究元审计报告渲染。"""

from __future__ import annotations

from typing import Any


def render_report(
    rows: list[dict[str, Any]],
    summary: dict[str, float],
    annual_breadth: list[dict[str, float]],
    comparator: dict[str, Any],
    pending: list[dict[str, str]],
    as_of_date: str,
) -> str:
    """生成验证窗口偏差审计报告。"""
    ordered = sorted(rows, key=lambda item: item["validation_sharpe"], reverse=True)
    experiment_rows = "\n".join(
        f"| {item['experiment_id']} | {item['validation_return']:.2%} | "
        f"{item['locked_return']:.2%} | {item['return_decay']:.2%} | "
        f"{item['validation_sharpe']:.3f} | {item['locked_sharpe']:.3f} | "
        f"{'是' if item['validation_core_pass'] else '否'} | "
        f"{'是' if item['locked_core_pass'] else '否'} |"
        for item in ordered
    )
    annual_rows = "\n".join(
        f"| {int(item['year'])} | {int(item['experiment_count'])} | "
        f"{item['median_return']:.2%} | {item['positive_ratio']:.1%} |"
        for item in annual_breadth
    )
    comparator_full = comparator.get("period_metrics", {}).get("full", {})
    evidence_status = (
        f"- **证据状态：未完成。仍有 {len(pending)} 个风险层口径变更实验待复验，"
        "下表仅包含当前有效结果，不作为最终因子排名。**"
        if pending
        else "- **证据状态：完整。所有纳入实验均通过当前口径校验。**"
    )
    blocked_note = (
        "当前有风险层口径复验尚未完成，因此暂停发布跨因子最终排序。"
        "以下统计只能用于识别流程风险，不能用于选择生产因子。"
        if pending
        else ""
    )
    return f"""# 跨因子研究稳健性元审计 V1

- 数据截止：{as_of_date}。
- 纳入 {int(summary['experiment_count'])} 个独立研究家族的最新版本。
- 只使用实验仓库结构化结果，不读取Markdown报告。
- 同一家族按末尾 `_vN` 折叠，防止迭代版本重复计票。
{evidence_status}

## 验证到锁定期衰减

- 年化收益中位数：验证期 {summary['median_validation_return']:.2%}，
  锁定期 {summary['median_locked_return']:.2%}，衰减
  {summary['median_return_decay']:.2%}。
- Sharpe中位数：验证期 {summary['median_validation_sharpe']:.3f}，
  锁定期 {summary['median_locked_sharpe']:.3f}，衰减
  {summary['median_sharpe_decay']:.3f}。
- 正收益比例：验证期 {summary['validation_positive_ratio']:.1%}，
  锁定期 {summary['locked_positive_ratio']:.1%}。
- 验证期核心门槛通过 {int(summary['validation_core_pass_count'])} 个，
  锁定期通过 {int(summary['locked_core_pass_count'])} 个。
- 验证期通过者的锁定期失效率：
  {summary['validation_false_discovery_ratio']:.1%}。
- 验证与锁定收益排名Spearman：
  {summary['return_rank_spearman']:.3f}；Sharpe排名：
  {summary['sharpe_rank_spearman']:.3f}。
- 验证期Top25%在锁定期仍处于Top25%的比例：
  {summary['validation_top_quartile_locked_persistence']:.1%}。
- 与Quality日收益相关性中位数：
  {summary['median_quality_correlation']:.3f}。

| 实验 | 验证年化 | 锁定年化 | 衰减 | 验证Sharpe | 锁定Sharpe | 验证过门槛 | 锁定过门槛 |
|---|---:|---:|---:|---:|---:|---|---|
{experiment_rows}

## 年度广度

| 年份 | 实验数 | 收益中位数 | 正收益比例 |
|---:|---:|---:|---:|
{annual_rows}

## 多折流程对照

Quality Balanced Value 使用2015至2017、2018至2020、2021至2023、
2024至最新四个互不重叠折，而不是单押2019至2021。其全样本年化
{float(comparator_full.get('annualized_return', float('nan'))):.2%}、Sharpe
{float(comparator_full.get('sharpe', float('nan'))):.3f}、最大回撤
{float(comparator_full.get('max_drawdown', float('nan'))):.2%}。

## 结论

{blocked_note}

2019至2021单一验证窗口存在系统性乐观偏差，且验证期排名无法稳定迁移到
2022年后的锁定样本。后续新因子不再以该单一窗口作为选拔依据，必须先通过
互不重叠的多折稳定性门槛，再保留最后一段完全锁定样本。

当前实验产物没有统一保存逐期市值和行业暴露，因此本报告不能把共同衰减
直接归因为小盘或行业集中；这是证据缺口，不做推测性结论。
"""
