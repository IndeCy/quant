"""持久化风险上限与权重约束测试。"""

from pathlib import Path

from runtime.risk_policy import RiskPolicyRepository, apply_risk_cap


def test_risk_policy_is_resolved_as_of_and_can_be_released(tmp_path: Path) -> None:
    """风险事件必须按生效日读取，未来决定不能污染历史。"""
    repository = RiskPolicyRepository(tmp_path / "state.sqlite")
    repository.activate("strategy-a", "20260720", 0.3, source_ack_id="ack-1")

    assert repository.resolve("strategy-a", "20260719") is None
    assert repository.resolve("strategy-a", "20260720").max_exposure == 0.3
    assert [policy.strategy_id for policy in repository.list_active("20260724")] == ["strategy-a"]

    repository.release("strategy-a", "20260725", reason="人工确认解除")

    assert repository.resolve("strategy-a", "20260724").max_exposure == 0.3
    assert repository.resolve("strategy-a", "20260725") is None
    assert repository.list_active("20260725") == []


def test_apply_risk_cap_preserves_relative_weights() -> None:
    """风险层只能缩放总暴露，不得改变策略内部选股比例。"""
    capped = apply_risk_cap({"A": 0.6, "B": 0.3}, 0.3)

    assert round(sum(capped.values()), 10) == 0.3
    assert round(capped["A"] / capped["B"], 10) == 2.0
