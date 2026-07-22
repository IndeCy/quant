"""风险恢复人工确认闭环测试。"""

from datetime import datetime
from pathlib import Path

from runtime.paths import RuntimePaths
from runtime.risk_policy import RiskPolicyRepository
from runtime.risk_recovery import RiskRecoveryAssessment, RiskRecoveryRepository
from runtime.risk_recovery_service import confirm_risk_recovery


def test_approve_recovery_changes_cap_next_trading_day_and_replans(tmp_path: Path) -> None:
    """批准恢复不能改写当天风险状态，必须下一交易日生效并重算委托。"""
    paths, recommendation_id = _seed_pending_recovery(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_replan(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"status": "SUCCESS", "message": "旧单取消1笔，新建1笔"}

    result = confirm_risk_recovery(
        paths,
        recommendation_id,
        "APPROVE",
        now=datetime(2026, 7, 6, 17, 10),
        replan_runner=fake_replan,
    )

    policies = RiskPolicyRepository(paths.system_state_path)
    assert policies.resolve("strategy-a", "20260706").max_exposure == 0.3
    assert policies.resolve("strategy-a", "20260707").max_exposure == 0.5
    assert result["recommendation"]["status"] == "APPROVED"
    assert calls[0]["effective_date"] == "20260707"
    assert calls[0]["signal_date"] == "20260706"


def test_keep_recovery_preserves_current_cap(tmp_path: Path) -> None:
    """人工选择继续限仓时，不得写入新的风险上限事件。"""
    paths, recommendation_id = _seed_pending_recovery(tmp_path)

    result = confirm_risk_recovery(paths, recommendation_id, "KEEP")

    assert result["recommendation"]["status"] == "KEPT"
    assert RiskPolicyRepository(paths.system_state_path).resolve("strategy-a", "20260710").max_exposure == 0.3


def _seed_pending_recovery(tmp_path: Path) -> tuple[RuntimePaths, str]:
    paths = RuntimePaths(tmp_path / "runtime")
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
        latest_volatility_20=0.3,
        eligible=True,
        reason="连续稳定3日",
    )
    recommendation, _ = RiskRecoveryRepository(paths.system_state_path).create_pending(assessment)
    return paths, str(recommendation["recommendation_id"])
