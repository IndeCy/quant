"""盘后实盘风险处置层。

该模块不改变 alpha 策略，也不自动下单；只把风险事件转成次日人工确认清单。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.notification_config import send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


RISK_GUARD_ID = "live_risk_guard"


@dataclass(frozen=True)
class RiskGuardResult:
    """盘后风控结果。"""

    trade_date: str
    status: str
    action_count: int
    report_path: str
    actions_path: str


def run_live_risk_guard(
    paths: RuntimePaths | None = None,
    trade_date: str | None = None,
    push: bool = False,
) -> RiskGuardResult:
    """运行盘后风险处置检查，异常时生成次日人工确认清单。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = trade_date or datetime.now().strftime("%Y%m%d")
    run_dir = runtime_paths.runs_dir / target_date
    run_dir.mkdir(parents=True, exist_ok=True)
    actions = _build_risk_actions(runtime_paths, target_date)
    status = _overall_status(actions)
    actions_path = run_dir / "risk_actions.csv"
    report_path = run_dir / "risk_guard_report.md"
    actions.to_csv(actions_path, index=False)
    report_path.write_text(_format_report(target_date, status, actions), encoding="utf-8")

    repository = SystemRepository(runtime_paths.system_state_path)
    repository.record_strategy_run(RISK_GUARD_ID, target_date, status, run_dir, f"risk_actions={len(actions)}")
    repository.record_run_step(RISK_GUARD_ID, target_date, 1, "risk_scan", status, f"risk_actions={len(actions)}", run_dir)
    if not actions.empty and push:
        send_bark_notification("量化风险处置触发", _format_notification(target_date, actions))
    return RiskGuardResult(
        trade_date=target_date,
        status=status,
        action_count=len(actions),
        report_path=str(report_path),
        actions_path=str(actions_path),
    )


def _build_risk_actions(paths: RuntimePaths, trade_date: str) -> pd.DataFrame:
    monitoring = MonitoringRepository(paths.monitoring_path)
    rows: list[dict[str, Any]] = []
    for strategy in _latest_strategy_metrics(monitoring, trade_date):
        severity, reasons = _classify_strategy_risk(strategy)
        if severity == "NORMAL":
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "strategy_id": strategy["strategy_id"],
                "strategy_name": strategy["strategy_name"],
                "severity": severity,
                "action_status": "NEED_CONFIRM",
                "suggested_action": "T+1开盘前复核，人工确认是否风险减仓",
                "daily_return": float(strategy["daily_return"]),
                "drawdown": float(strategy["drawdown"]),
                "volatility_20": float(strategy["volatility_20"]),
                "exposure": float(strategy["exposure"]),
                "reasons": "；".join(reasons),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "trade_date",
            "strategy_id",
            "strategy_name",
            "severity",
            "action_status",
            "suggested_action",
            "daily_return",
            "drawdown",
            "volatility_20",
            "exposure",
            "reasons",
        ],
    )


def _latest_strategy_metrics(monitoring: MonitoringRepository, trade_date: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with monitoring._connect() as con:  # noqa: SLF001 - 仓库暂未暴露按日列出接口。
        rows = con.execute(
            """
            SELECT * FROM strategy_nav_daily
            WHERE trade_date = ?
            ORDER BY strategy_id
            """,
            [trade_date],
        ).fetchall()
        columns = [item[1] for item in con.execute("PRAGMA table_info(strategy_nav_daily)").fetchall()]
    for row in rows:
        result.append(dict(zip(columns, row)))
    return result


def _classify_strategy_risk(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    daily_return = float(metrics.get("daily_return") or 0.0)
    drawdown = float(metrics.get("drawdown") or 0.0)
    volatility = float(metrics.get("volatility_20") or 0.0)
    reasons: list[str] = []
    critical = False
    warning = False
    if daily_return <= -0.08:
        critical = True
        reasons.append(f"当日收益 {daily_return:.2%} <= -8%")
    elif daily_return <= -0.05:
        warning = True
        reasons.append(f"当日收益 {daily_return:.2%} <= -5%")
    if drawdown <= -0.20:
        critical = True
        reasons.append(f"当前回撤 {drawdown:.2%} <= -20%")
    elif drawdown <= -0.10:
        warning = True
        reasons.append(f"当前回撤 {drawdown:.2%} <= -10%")
    if volatility >= 0.50:
        critical = True
        reasons.append(f"20日波动率 {volatility:.2%} >= 50%")
    return ("CRITICAL" if critical else "WARNING" if warning else "NORMAL", reasons)


def _overall_status(actions: pd.DataFrame) -> str:
    if actions.empty:
        return "NORMAL"
    if actions["severity"].eq("CRITICAL").any():
        return "CRITICAL"
    return "WARNING"


def _format_report(trade_date: str, status: str, actions: pd.DataFrame) -> str:
    if actions.empty:
        return f"# 盘后风险处置报告\n\n- 交易日：{trade_date}\n- 状态：NORMAL\n- 风险操作：无\n"
    lines = ["# 盘后风险处置报告", "", f"- 交易日：{trade_date}", f"- 状态：{status}", "- 风险操作：需要人工确认", ""]
    for _, row in actions.iterrows():
        lines.extend(
            [
                f"## {row['strategy_name']}",
                "",
                f"- 严重级别：{row['severity']}",
                f"- 当前仓位：{float(row['exposure']):.2%}",
                f"- 当日收益：{float(row['daily_return']):.2%}",
                f"- 当前回撤：{float(row['drawdown']):.2%}",
                f"- 20日波动率：{float(row['volatility_20']):.2%}",
                f"- 建议：{row['suggested_action']}",
                f"- 原因：{row['reasons']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _format_notification(trade_date: str, actions: pd.DataFrame) -> str:
    lines = [f"量化风险处置触发 {trade_date}", "", "明日开盘前复核：需要", ""]
    for _, row in actions.iterrows():
        lines.extend(
            [
                f"{row['strategy_name']}：{row['severity']}",
                f"- 当日收益：{float(row['daily_return']):.2%}",
                f"- 当前回撤：{float(row['drawdown']):.2%}",
                f"- 20日波动率：{float(row['volatility_20']):.2%}",
                f"- 建议：{row['suggested_action']}",
                "",
            ]
        )
    return "\n".join(lines).strip()
