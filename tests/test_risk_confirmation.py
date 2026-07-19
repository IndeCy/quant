"""盘前风险确认状态测试。"""

from pathlib import Path

import pandas as pd

from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.risk_confirmation import (
    PAUSE_DECISION,
    PROCEED_DECISION,
    REDUCE_DECISION,
    blocked_strategy_ids,
    build_risk_confirmation_state,
    record_risk_confirmation,
    risk_reduction_targets,
)


def test_risk_confirmation_requires_explicit_decision_and_persists_choice(tmp_path: Path) -> None:
    """风险任务默认阻断，明确允许后才从门禁集合移除。"""
    paths = RuntimePaths(tmp_path / "runtime")
    _seed_risk(paths)

    pending = build_risk_confirmation_state(paths, "20260720")
    assert pending["previous_trade_date"] == "20260717"
    assert pending["status"] == "NEED_CONFIRM"
    assert blocked_strategy_ids(pending) == {"mainline_chain_factor_v1"}

    allowed = record_risk_confirmation(paths, "mainline_chain_factor_v1", "20260720", PROCEED_DECISION)
    assert allowed["status"] == "READY"
    assert allowed["tasks"][0]["status"] == "CONFIRMED_PROCEED"
    assert blocked_strategy_ids(allowed) == set()

    paused = record_risk_confirmation(paths, "mainline_chain_factor_v1", "20260720", PAUSE_DECISION)
    assert paused["status"] == "PAUSED"
    assert blocked_strategy_ids(paused) == {"mainline_chain_factor_v1"}

    reduced = record_risk_confirmation(paths, "mainline_chain_factor_v1", "20260720", REDUCE_DECISION)
    assert reduced["status"] == "REDUCTION_READY"
    assert reduced["tasks"][0]["status"] == "CONFIRMED_REDUCE"
    assert blocked_strategy_ids(reduced) == set()
    assert risk_reduction_targets(reduced) == {"mainline_chain_factor_v1": 0.3}


def _seed_risk(paths: RuntimePaths) -> None:
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
