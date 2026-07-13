"""运维质量趋势报告。

把操作判断、人工确认和闭环指标写入统一报告索引，便于日报/月报视角复盘。
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Mapping

from runtime.operations_ack import list_operations_ack
from runtime.operations_review import build_operations_review
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def build_operations_quality_report(
    paths: RuntimePaths,
    readiness: Mapping[str, object] | None = None,
    trade_date: str | None = None,
) -> dict[str, object]:
    """生成并登记运维质量趋势报告。"""
    paths.ensure_directories()
    target_date = trade_date or datetime.now().strftime("%Y%m%d")
    output_dir = paths.reports_dir / "operations_quality" / target_date
    output_dir.mkdir(parents=True, exist_ok=True)
    review = build_operations_review(paths.root, paths.system_state_path, readiness)
    acknowledgements = list_operations_ack(paths.system_state_path, limit=20)
    payload = {
        "trade_date": target_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "review": review,
        "acknowledgements": acknowledgements,
    }
    markdown_path = output_dir / "operations_quality_review.md"
    json_path = output_dir / "operations_quality_review.json"
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    SystemRepository(paths.system_state_path).upsert_report(
        report_type="operations_quality_review",
        strategy_id="operations",
        trade_date=target_date,
        title=f"运维质量趋势 {target_date}",
        file_path=markdown_path,
        tags=["operations", "quality", "review"],
    )
    return {
        "trade_date": target_date,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "review": review,
    }


def _render_markdown(payload: Mapping[str, object]) -> str:
    review = payload.get("review", {})
    acknowledgements = payload.get("acknowledgements", [])
    lines = [
        "# 运维质量趋势",
        "",
        f"- 交易日：{payload.get('trade_date', '')}",
        f"- 生成时间：{payload.get('generated_at', '')}",
        "",
        "## 闭环指标",
        "",
    ]
    if isinstance(review, Mapping):
        lines.extend(
            [
                f"- 闭环状态：{review.get('closure_status', '')}",
                f"- 最新决策：{review.get('latest_decision', '')}",
                f"- 当前告警数：{review.get('current_action_count', 0)}",
                f"- 已确认告警数：{review.get('acknowledged_action_count', 0)}",
                f"- 待跟进告警数：{review.get('unacknowledged_action_count', 0)}",
                f"- 确认记录总数：{review.get('acknowledgement_count', 0)}",
                f"- 最近确认时间：{review.get('latest_ack_at', '') or '暂无'}",
            ]
        )
    lines.extend(["", "## 最近确认记录", "", "| 日期 | 项目 | 状态 | 处置 |", "|---|---|---|---|"])
    if isinstance(acknowledgements, list) and acknowledgements:
        for item in acknowledgements[:10]:
            if isinstance(item, Mapping):
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            str(item.get("trade_date", "")),
                            str(item.get("name", "")),
                            str(item.get("status", "")),
                            str(item.get("resolution", "")),
                        ]
                    )
                    + " |"
                )
    else:
        lines.append("| - | 无 | - | - |")
    lines.append("")
    return "\n".join(lines)
