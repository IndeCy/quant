"""主线链动策略监控适配层。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pandas as pd

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


MAINLINE_STRATEGY_ID = "mainline_chain_b"
MAINLINE_STRATEGY_NAME = "主线链动策略"
MAINLINE_STRATEGY_CODE = "Mainline_Chain_Momentum"


def sync_mainline_chain_monitoring(
    paths: RuntimePaths | None = None,
    monitoring_repository: MonitoringRepository | None = None,
    system_repository: SystemRepository | None = None,
) -> dict[str, Any]:
    """把主线链动模拟盘快照同步为统一监控指标和运行记录。"""
    runtime_paths = paths or get_runtime_paths()
    if not runtime_paths.paper_trading_path.exists():
        return {"account_id": None, "snapshot_count": 0, "latest_trade_date": None}

    account = _load_mainline_account(runtime_paths.paper_trading_path)
    if account is None:
        return {"account_id": None, "snapshot_count": 0, "latest_trade_date": None}

    snapshots = _load_snapshots(runtime_paths.paper_trading_path, int(account["id"]))
    if snapshots.empty:
        return {"account_id": int(account["id"]), "snapshot_count": 0, "latest_trade_date": None}

    monitor = monitoring_repository or MonitoringRepository(runtime_paths.monitoring_path)
    system = system_repository or SystemRepository(runtime_paths.system_state_path)
    frame = _build_monitor_frame(account, snapshots)
    monitor.upsert_strategy_daily(frame)
    _record_runs(system, runtime_paths, snapshots)

    latest_trade_date = str(frame.iloc[-1]["trade_date"])
    return {
        "account_id": int(account["id"]),
        "snapshot_count": int(len(snapshots)),
        "latest_trade_date": latest_trade_date,
    }


def _load_mainline_account(path: Any) -> dict[str, Any] | None:
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            SELECT * FROM paper_account
            WHERE strategy_code = ?
            ORDER BY id
            LIMIT 1
            """,
            [MAINLINE_STRATEGY_CODE],
        ).fetchone()
    return dict(row) if row else None


def _load_snapshots(path: Any, account_id: int) -> pd.DataFrame:
    with sqlite3.connect(path) as con:
        frame = pd.read_sql_query(
            """
            SELECT * FROM paper_daily_snapshot
            WHERE account_id = ?
            ORDER BY trade_date
            """,
            con,
            params=[account_id],
        )
    return frame


def _build_monitor_frame(account: dict[str, Any], snapshots: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(snapshots["trade_date"]).dt.normalize()
    initial_cash = float(account["initial_cash"] or snapshots.iloc[0]["total_value"])
    strategy_returns = snapshots["strategy_return"].astype(float).values
    benchmark_returns = snapshots["benchmark_return"].astype(float).values
    strategy_values = pd.Series(initial_cash * (1.0 + strategy_returns), index=dates)
    benchmark_values = pd.Series(initial_cash * (1.0 + benchmark_returns), index=dates)
    total_value = snapshots["total_value"].astype(float).replace(0, pd.NA)
    exposure = pd.Series(
        (snapshots["position_value"].astype(float) / total_value).fillna(0.0).values,
        index=dates,
    )
    return build_strategy_monitor_frame(
        strategy_id=MAINLINE_STRATEGY_ID,
        strategy_name=MAINLINE_STRATEGY_NAME,
        daily_values=strategy_values,
        benchmark_values=benchmark_values,
        exposure=exposure,
        benchmark_id=str(account.get("benchmark_symbol") or "000001.SH"),
    )


def _record_runs(system: SystemRepository, paths: RuntimePaths, snapshots: pd.DataFrame) -> None:
    for row in snapshots.to_dict(orient="records"):
        trade_date = pd.to_datetime(row["trade_date"]).strftime("%Y%m%d")
        message = f"最强产业链: {row.get('strongest_chain') or '-'}, 信号: {row.get('rebalance_signal') or '-'}"
        system.record_strategy_run(
            MAINLINE_STRATEGY_ID,
            trade_date,
            "SUCCESS",
            paths.paper_trading_path,
            message,
        )
        targets = json.loads(row.get("target_symbols") or "[]")
        system.record_run_step(
            MAINLINE_STRATEGY_ID,
            trade_date,
            1,
            "paper_snapshot_sync",
            "SUCCESS",
            f"同步模拟盘快照，目标 {len(targets)} 只",
            paths.paper_trading_path,
        )
