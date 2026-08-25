"""风险仓位恢复评估与持久化测试。"""

from pathlib import Path

import pandas as pd

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.live_risk_guard import run_live_risk_guard
from runtime.risk_policy import RiskPolicyRepository
from runtime.risk_recovery import (
    RiskRecoveryRepository,
    assess_risk_recoveries,
    sync_recovery_recommendations,
)


def test_recovery_requires_three_stable_days_and_raises_one_level(tmp_path: Path) -> None:
    """30% 上限只能在三日稳定、回撤修复后建议提高到 50%。"""
    paths = _seed_history(tmp_path, current_cap=0.3)

    assessment = assess_risk_recoveries(paths, "20260706")[0]

    assert assessment.eligible is True
    assert assessment.stable_days_observed == 3
    assert assessment.current_cap == 0.3
    assert assessment.recommended_cap == 0.5
    assert assessment.recommendation_action == "INCREASE"


def test_recovery_waits_when_stable_days_or_volatility_is_insufficient(tmp_path: Path) -> None:
    """稳定天数不足或波动率仍高时不能生成恢复建议。"""
    paths = _seed_history(tmp_path, current_cap=0.3, volatilities=[0.30, 0.30, 0.48])

    assessment = assess_risk_recoveries(paths, "20260706")[0]
    _, created = sync_recovery_recommendations(paths, "20260706")

    assert assessment.eligible is False
    assert assessment.stable_days_observed == 0
    assert created == []


def test_full_release_requires_normal_risk_state(tmp_path: Path) -> None:
    """70% 到 100% 属于完全解除，当前风险状态必须恢复为 NORMAL。"""
    paths = _seed_history(
        tmp_path,
        current_cap=0.7,
        drawdowns=[-0.12, -0.10, -0.08],
    )

    assessment = assess_risk_recoveries(paths, "20260706")[0]

    assert assessment.eligible is True
    assert assessment.current_severity == "NORMAL"
    assert assessment.recommended_cap == 1.0
    assert assessment.recommendation_action == "RELEASE"


def test_recovery_recommendation_is_idempotent_for_bark(tmp_path: Path) -> None:
    """同一天重复执行盘后守卫，只能首次产生一条待通知建议。"""
    paths = _seed_history(tmp_path, current_cap=0.3)

    _, first = sync_recovery_recommendations(paths, "20260706")
    _, second = sync_recovery_recommendations(paths, "20260706")

    assert len(first) == 1
    assert second == []
    assert len(RiskRecoveryRepository(paths.system_state_path).list_pending()) == 1


def test_live_guard_sends_recovery_bark_only_once(monkeypatch, tmp_path: Path) -> None:
    """恢复条件首次满足时发送 Bark，盘后任务重跑不能重复通知。"""
    paths = _seed_history(tmp_path, current_cap=0.3)
    notifications: list[str] = []
    monkeypatch.setattr(
        "runtime.live_risk_guard.send_bark_notification",
        lambda title, body: notifications.append(title),
    )

    first = run_live_risk_guard(paths, trade_date="20260706", push=True)
    second = run_live_risk_guard(paths, trade_date="20260706", push=True)

    assert first.recovery_count == 1
    assert second.recovery_count == 0
    assert notifications == ["风险仓位恢复待确认"]


def _seed_history(
    tmp_path: Path,
    *,
    current_cap: float,
    volatilities: list[float] | None = None,
    drawdowns: list[float] | None = None,
) -> RuntimePaths:
    """构造风险上限生效后的三个交易日监控事实。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    RiskPolicyRepository(paths.system_state_path).activate("strategy-a", "20260701", current_cap)
    dates = ["20260702", "20260703", "20260706"]
    vols = volatilities or [0.30, 0.29, 0.28]
    dds = drawdowns or [-0.22, -0.20, -0.18]
    frame = pd.DataFrame(
        [
            {
                "trade_date": date,
                "strategy_id": "strategy-a",
                "strategy_name": "策略A",
                "nav": 1.0,
                "daily_return": 0.01,
                "cumulative_return": 0.0,
                "benchmark_id": "510300",
                "benchmark_nav": 1.0,
                "benchmark_return": 0.0,
                "excess_return": 0.0,
                "drawdown": drawdown,
                "max_drawdown": min(dds),
                "volatility_20": volatility,
                "volatility_60": volatility,
                "sharpe_rolling": 0.0,
                "exposure": 1.0,
                "turnover_notional": 0.0,
                "total_execution_cost": 0.0,
                "failed_order_count": 0,
            }
            for date, volatility, drawdown in zip(dates, vols, dds)
        ]
    )
    MonitoringRepository(paths.monitoring_path).upsert_strategy_daily(frame)
    return paths
