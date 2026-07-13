"""开盘前风险复核。

读取上一交易日盘后风险单，生成当天人工执行检查清单；不自动下单。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from runtime.notification_config import send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


PRE_MARKET_ID = "pre_market_check"


@dataclass(frozen=True)
class PreMarketCheckResult:
    """开盘前复核结果。"""

    trade_date: str
    previous_trade_date: str
    status: str
    item_count: int
    checklist_path: str
    report_path: str


def run_pre_market_check(
    paths: RuntimePaths | None = None,
    trade_date: str | None = None,
    previous_trade_date: str | None = None,
    push: bool = False,
) -> PreMarketCheckResult:
    """运行开盘前风险复核，有待确认项时发送 Bark。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = trade_date or datetime.now().strftime("%Y%m%d")
    prev_date = previous_trade_date or _previous_calendar_day(target_date)
    run_dir = runtime_paths.runs_dir / target_date
    run_dir.mkdir(parents=True, exist_ok=True)
    actions = _load_previous_actions(runtime_paths.runs_dir / prev_date / "risk_actions.csv")
    checklist = _build_checklist(target_date, prev_date, actions)
    status = "NEED_CONFIRM" if not checklist.empty else "NO_ACTION"
    checklist_path = run_dir / "execution_checklist.csv"
    report_path = run_dir / "pre_market_check.md"
    checklist.to_csv(checklist_path, index=False)
    report_path.write_text(_format_report(target_date, prev_date, status, checklist), encoding="utf-8")
    SystemRepository(runtime_paths.system_state_path).record_strategy_run(
        PRE_MARKET_ID,
        target_date,
        status,
        run_dir,
        f"items={len(checklist)} previous_trade_date={prev_date}",
    )
    if not checklist.empty and push:
        send_bark_notification("开盘前风险复核", _format_notification(target_date, prev_date, checklist))
    return PreMarketCheckResult(
        trade_date=target_date,
        previous_trade_date=prev_date,
        status=status,
        item_count=len(checklist),
        checklist_path=str(checklist_path),
        report_path=str(report_path),
    )


def _load_previous_actions(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame()
    return frame[frame.get("action_status", "").eq("NEED_CONFIRM")].copy()


def _build_checklist(trade_date: str, previous_trade_date: str, actions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in actions.iterrows():
        rows.append(
            {
                "trade_date": trade_date,
                "previous_trade_date": previous_trade_date,
                "strategy_id": row.get("strategy_id", ""),
                "strategy_name": row.get("strategy_name", ""),
                "severity": row.get("severity", ""),
                "check_status": "PENDING_MANUAL_CONFIRM",
                "tradability_check": "待人工确认停牌/跌停/集合竞价",
                "suggested_action": row.get("suggested_action", "人工确认风险减仓"),
                "reasons": row.get("reasons", ""),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "trade_date",
            "previous_trade_date",
            "strategy_id",
            "strategy_name",
            "severity",
            "check_status",
            "tradability_check",
            "suggested_action",
            "reasons",
        ],
    )


def _format_report(trade_date: str, previous_trade_date: str, status: str, checklist: pd.DataFrame) -> str:
    if checklist.empty:
        return f"# 开盘前风险复核\n\n- 日期：{trade_date}\n- 昨日风险单：0 条\n- 状态：NO_ACTION\n"
    lines = [
        "# 开盘前风险复核",
        "",
        f"- 日期：{trade_date}",
        f"- 上一风险日：{previous_trade_date}",
        f"- 昨日风险单：{len(checklist)} 条",
        f"- 状态：{status}",
        "",
    ]
    for _, row in checklist.iterrows():
        lines.extend(
            [
                f"## {row['strategy_name']}",
                "",
                f"- 严重级别：{row['severity']}",
                f"- 可交易性检查：{row['tradability_check']}",
                f"- 建议：{row['suggested_action']}",
                f"- 原因：{row['reasons']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _format_notification(trade_date: str, previous_trade_date: str, checklist: pd.DataFrame) -> str:
    lines = [f"开盘前风险复核 {trade_date}", "", f"昨日风险单：{len(checklist)} 条", f"上一风险日：{previous_trade_date}", ""]
    for _, row in checklist.iterrows():
        lines.extend(
            [
                f"{row['strategy_name']}：{row['severity']}",
                f"- 可交易性：{row['tradability_check']}",
                f"- 建议：{row['suggested_action']}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _previous_calendar_day(trade_date: str) -> str:
    date_value = datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=1)
    return date_value.strftime("%Y%m%d")
