"""风险确认与开盘撮合闭环测试。"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.market_open_paper_execution import MarketOpenExecutionResult
from runtime.paths import RuntimePaths
from runtime.risk_confirmation import PAUSE_DECISION, REDUCE_DECISION
from runtime.risk_confirmation_service import confirm_risk_action


def test_intraday_reduction_confirmation_reuses_market_open_executor(tmp_path: Path) -> None:
    """09:35之后确认减仓应立即进入统一撮合入口，而非只保存记录。"""
    paths = _seed_risk(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_runner(**kwargs) -> MarketOpenExecutionResult:
        calls.append(kwargs)
        return MarketOpenExecutionResult("20260720", "SUCCESS", 2, 1, 0, 0, 1, 1)

    state = confirm_risk_action(
        paths,
        "mainline_chain_factor_v1",
        "20260720",
        REDUCE_DECISION,
        now=datetime(2026, 7, 20, 11, 50),
        execution_runner=fake_runner,
    )

    assert calls == [{"paths": paths, "trade_date": "20260720", "push": False}]
    assert state["execution"]["status"] == "SUCCESS"
    assert state["execution"]["risk_reduction_orders"] == 1


def test_preopen_confirmation_waits_and_pause_never_executes(tmp_path: Path) -> None:
    """开盘前确认等待09:35；暂停决定在任何时点都不能触发撮合。"""
    paths = _seed_risk(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_runner(**kwargs) -> MarketOpenExecutionResult:
        calls.append(kwargs)
        return MarketOpenExecutionResult("20260720", "SUCCESS", 0, 0, 0)

    waiting = confirm_risk_action(
        paths,
        "mainline_chain_factor_v1",
        "20260720",
        REDUCE_DECISION,
        now=datetime(2026, 7, 20, 9, 30),
        execution_runner=fake_runner,
    )
    paused = confirm_risk_action(
        paths,
        "mainline_chain_factor_v1",
        "20260720",
        PAUSE_DECISION,
        now=datetime(2026, 7, 20, 10, 0),
        execution_runner=fake_runner,
    )

    assert waiting["execution"]["status"] == "SCHEDULED"
    assert paused["execution"]["status"] == "PAUSED"
    assert calls == []


def _seed_risk(tmp_path: Path) -> RuntimePaths:
    """构造上一交易日触发风险的监控事实。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    dates = pd.to_datetime(["2026-07-16", "2026-07-17"])
    frame = build_strategy_monitor_frame(
        strategy_id="mainline_chain_factor_v1",
        strategy_name="主线链动因子 V1",
        daily_values=pd.Series([100.0, 91.0], index=dates),
        benchmark_values=pd.Series([1.0, 1.0], index=dates),
        exposure=pd.Series([1.0, 0.95], index=dates),
    )
    frame.loc[frame.index[-1], "daily_return"] = -0.09
    frame.loc[frame.index[-1], "drawdown"] = -0.21
    frame.loc[frame.index[-1], "volatility_20"] = 0.55
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)
    return paths
