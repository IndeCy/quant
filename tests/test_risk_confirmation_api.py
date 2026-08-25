"""盘前风险确认 API 测试。"""

import pandas as pd
from fastapi.testclient import TestClient

from api.local_server import create_app
from api.service import LocalApiService
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.risk_policy import RiskPolicyRepository
from runtime.risk_recovery import RiskRecoveryAssessment, RiskRecoveryRepository


def test_risk_confirmation_api_lists_and_confirms_task(tmp_path) -> None:
    """前端应能读取风险任务并明确选择允许撮合。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    _seed_risk(paths)
    client = TestClient(create_app(LocalApiService(paths)))

    pending = client.get("/api/risk-confirmations?trade_date=20260720")
    assert pending.status_code == 200
    assert pending.json()["status"] == "NEED_CONFIRM"
    assert "recovery" in pending.json()

    confirmed = client.post(
        "/api/risk-confirmations/mainline_chain_factor_v1",
        json={"trade_date": "20260720", "decision": "PROCEED"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "READY"
    assert confirmed.json()["tasks"][0]["decision"] == "PROCEED"

    reduced = client.post(
        "/api/risk-confirmations/mainline_chain_factor_v1",
        json={"trade_date": "20260720", "decision": "REDUCE"},
    )
    assert reduced.status_code == 200
    assert reduced.json()["status"] == "REDUCTION_READY"
    assert reduced.json()["tasks"][0]["decision"] == "REDUCE"


def test_risk_recovery_api_can_keep_current_cap(tmp_path) -> None:
    """调度页可以选择继续限仓，且不会误写风险恢复事件。"""
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    RiskPolicyRepository(paths.system_state_path).activate("strategy-a", "20260701", 0.3)
    assessment = RiskRecoveryAssessment(
        strategy_id="strategy-a",
        strategy_name="策略A",
        trade_date="20260706",
        policy_effective_date="20260701",
        current_cap=0.3,
        recommended_cap=0.5,
        recommendation_action="INCREASE",
        current_severity="WARNING",
        stable_days_observed=3,
        stable_days_required=3,
        drawdown_recovery=0.04,
        latest_drawdown=-0.18,
        latest_volatility_20=0.30,
        eligible=True,
        reason="连续稳定3日",
    )
    recommendation, _ = RiskRecoveryRepository(paths.system_state_path).create_pending(assessment)
    client = TestClient(create_app(LocalApiService(paths)))

    response = client.post(
        f"/api/risk-recoveries/{recommendation['recommendation_id']}",
        json={"decision": "KEEP"},
    )

    assert response.status_code == 200
    assert response.json()["recovery_execution"]["execution"]["status"] == "KEPT"
    assert RiskPolicyRepository(paths.system_state_path).resolve("strategy-a", "20260710").max_exposure == 0.3


def _seed_risk(paths: RuntimePaths) -> None:
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
