"""开盘前风险复核。

读取上一交易日盘后风险单，生成当天人工执行检查清单；不自动下单。
"""

from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from runtime.notification_config import send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.risk_confirmation import build_risk_confirmation_state


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
    state = build_risk_confirmation_state(runtime_paths, trade_date, previous_trade_date)
    target_date = str(state["trade_date"])
    prev_date = str(state["previous_trade_date"])
    run_dir = runtime_paths.runs_dir / target_date
    run_dir.mkdir(parents=True, exist_ok=True)
    checklist = _build_checklist(state)
    status = str(state["status"])
    checklist_path = run_dir / "execution_checklist.csv"
    report_path = run_dir / "pre_market_check.md"
    checklist.to_csv(checklist_path, index=False)
    report_path.write_text(_format_report(target_date, prev_date, status, checklist), encoding="utf-8")
    SystemRepository(runtime_paths.system_state_path).record_strategy_run(
        PRE_MARKET_ID,
        target_date,
        status,
        run_dir,
        f"items={len(checklist)} pending={state['pending_count']} previous_trade_date={prev_date}",
    )
    if int(state["pending_count"]) > 0 and push:
        send_bark_notification("开盘前风险复核", _format_notification(target_date, prev_date, checklist))
    return PreMarketCheckResult(
        trade_date=target_date,
        previous_trade_date=prev_date,
        status=status,
        item_count=len(checklist),
        checklist_path=str(checklist_path),
        report_path=str(report_path),
    )


def _build_checklist(state: dict[str, object]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    tasks = state.get("tasks", [])
    for task in tasks if isinstance(tasks, list) else []:
        rows.append(
            {
                "trade_date": state["trade_date"],
                "previous_trade_date": state["previous_trade_date"],
                "strategy_id": task.get("strategy_id", ""),
                "strategy_name": task.get("strategy_name", ""),
                "severity": task.get("severity", ""),
                "check_status": task.get("status", ""),
                "decision": task.get("decision", ""),
                "current_exposure": task.get("current_exposure", 0.0),
                "recommended_target_exposure": task.get("recommended_target_exposure", 0.0),
                "active_risk_cap": task.get("active_risk_cap"),
                "effective_target_exposure": task.get("effective_target_exposure", 0.0),
                "tradability_check": task.get("tradability_check", ""),
                "suggested_action": task.get("suggested_action", ""),
                "reasons": task.get("reasons", ""),
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
            "decision",
            "current_exposure",
            "recommended_target_exposure",
            "active_risk_cap",
            "effective_target_exposure",
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
                f"- 确认状态：{row['check_status']}",
                f"- 策略理论仓位：{float(row['current_exposure']):.2%}",
                f"- 建议风险仓位上限：{float(row['recommended_target_exposure']):.2%}",
                f"- 当前有效风险上限：{_optional_percent(row['active_risk_cap'])}",
                f"- 当前有效目标仓位：{float(row['effective_target_exposure']):.2%}",
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
                f"- 当前仓位：{float(row['current_exposure']):.2%}",
                f"- 建议上限：{float(row['recommended_target_exposure']):.2%}",
                f"- 可交易性：{row['tradability_check']}",
                f"- 建议：{row['suggested_action']}",
                "- 操作：请在调度页选择‘执行风险减仓’、‘允许原计划撮合’或‘暂停今日撮合’",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _optional_percent(value: object) -> str:
    """格式化可能尚未激活的风险上限。"""
    if value is None or pd.isna(value):
        return "未激活"
    return f"{float(value):.2%}"
