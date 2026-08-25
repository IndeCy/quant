"""Quality ML Ranker V0 研究报告渲染。"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ml.contracts import DatasetManifest


def render_quality_ml_report(
    *,
    manifest: DatasetManifest,
    selected_model_id: str,
    prediction_metrics: pd.DataFrame,
    backtest_metrics: pd.DataFrame,
    annual_metrics: pd.DataFrame,
    bucket_diagnostics: pd.DataFrame,
    walk_forward_windows: pd.DataFrame,
    promotion_gate: dict[str, Any],
) -> str:
    """生成包含数据门禁、样本外表现和晋级结论的报告。"""
    backtest = backtest_metrics.copy()
    for column in [
        "年化收益", "最大回撤", "超额收益", "年化换手率",
        "执行成本影响", "平均仓位", "Calmar",
    ]:
        if column in backtest:
            formatter = _format_number if column == "Calmar" else _format_percent
            backtest[column] = backtest[column].map(formatter)
    if "夏普比率" in backtest:
        backtest["夏普比率"] = backtest["夏普比率"].map(_format_number)

    predictions = prediction_metrics.copy()
    for column in predictions.columns:
        if column != "model_id":
            predictions[column] = predictions[column].map(_format_number)

    annual = annual_metrics.copy()
    for column in ["年度收益", "年度最大回撤", "年度超额收益"]:
        if column in annual:
            annual[column] = annual[column].map(_format_percent)

    buckets = bucket_diagnostics.copy()
    for column in ["average_forward_return", "win_rate"]:
        if column in buckets:
            buckets[column] = buckets[column].map(_format_percent)

    status = str(promotion_gate.get("status") or "FAIL")
    conclusion = (
        "通过研究门禁，可以进入独立 Paper 候选评审。"
        if status == "PASS"
        else "未通过研究门禁，不注册日常策略，也不进入 Paper。"
    )
    return "\n".join(
        [
            "# Quality ML Ranker V0",
            "",
            "## 研究边界",
            "",
            "- 输入仅为 ROE、ROA、OCF_TO_OR，不新增因子。",
            "- 股票池、Top20、月频、qfq、波动率风险层和 M0 T+1 成交与 Quality V1 一致。",
            "- 模型只输出连续信号分数，组合层决定 Top20 等权。",
            "- 模型参数在读取锁定测试集结果前已经冻结。",
            "",
            "## 数据门禁",
            "",
            f"- 数据集哈希：`{manifest.dataset_hash}`",
            f"- 样本数：{manifest.row_count:,}，可训练样本：{manifest.trainable_count:,}",
            f"- 信号区间：{manifest.first_signal_date} 至 {manifest.last_signal_date}",
            f"- 公告日穿越：{manifest.as_of_violation_count}",
            f"- 重复样本：{manifest.duplicate_count}",
            f"- 无有效未来标签：{manifest.invalid_label_count}",
            "",
            "## 模型预测诊断",
            "",
            _markdown_table(predictions),
            "",
            f"验证集固定规则选中：`{selected_model_id}`。",
            "",
            "## 锁定测试集 M0 回测",
            "",
            _markdown_table(backtest),
            "",
            "## 年度稳定性",
            "",
            _markdown_table(annual),
            "",
            "## 预测分桶",
            "",
            _markdown_table(buckets),
            "",
            "## Walk Forward 窗口",
            "",
            _markdown_table(walk_forward_windows),
            "",
            "## 晋级门禁",
            "",
            "```json",
            json.dumps(promotion_gate, ensure_ascii=False, indent=2),
            "```",
            "",
            f"**结论：{conclusion}**",
            "",
            "本报告不根据测试集结果调参；失败结果作为研究资产保留。",
        ]
    )


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无数据"
    text = frame.fillna("").astype(str)
    headers = list(text.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in text.itertuples(index=False):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _format_percent(value: object) -> str:
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return ""


def _format_number(value: object) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return ""
