"""Quality防守资产V2生产契约测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from runtime.strategy_definition_loader import load_strategy_definition
from strategies.quality_fixed_sleeve import (
    build_effective_exposure_series,
    build_fixed_sleeve_targets,
    load_fixed_sleeve_plan,
)


STRATEGY_ID = "quality_defensive_assets_core_scoped_70_15_15_v2"


def test_candidate_definition_freezes_core_scoped_risk_and_paper_policy() -> None:
    """进入长期Paper的必须是V2核心风险预算，不能误用已拒绝V1。"""
    definition = load_strategy_definition(STRATEGY_ID)
    instance = definition.to_instance_payload()

    plan = load_fixed_sleeve_plan(instance)

    assert definition.status == "paper"
    assert definition.enabled is True
    assert instance["config"]["score_mode"] == "quality_balanced_value_v1"
    assert instance["config"]["risk_scope"] == "quality_core_only"
    assert plan is not None
    assert plan.core_allocation == pytest.approx(0.70)
    assert plan.defensive_weights == {
        "518880.SH": pytest.approx(0.15),
        "511010.SH": pytest.approx(0.15),
    }
    policy = instance["config"]["paper_execution_policy"]
    assert policy["open_aware_order_sizing"] is True
    assert policy["execution_delay"] == 1
    assert set(policy["tax_exempt_symbols"]) == {"518880.SH", "511010.SH"}


def test_core_scoped_targets_keep_defensive_sleeves_when_core_reduces() -> None:
    """核心风险层降到30%时，黄金和国债仍各占15%，总暴露为51%。"""
    instance = load_strategy_definition(STRATEGY_ID).to_instance_payload()
    core_targets = {
        "20240131": {"000001.SZ": 0.5, "000002.SZ": 0.5},
    }
    exposure = pd.Series(
        [1.0, 0.3],
        index=pd.to_datetime(["2024-01-31", "2024-02-01"]),
    )

    targets = build_fixed_sleeve_targets(instance, core_targets, exposure)

    assert targets["20240131"] == {
        "000001.SZ": pytest.approx(0.35),
        "000002.SZ": pytest.approx(0.35),
        "518880.SH": pytest.approx(0.15),
        "511010.SH": pytest.approx(0.15),
    }
    assert targets["20240201"] == {
        "000001.SZ": pytest.approx(0.105),
        "000002.SZ": pytest.approx(0.105),
        "518880.SH": pytest.approx(0.15),
        "511010.SH": pytest.approx(0.15),
    }
    assert sum(targets["20240201"].values()) == pytest.approx(0.51)


def test_effective_exposure_carries_latest_target_between_rebalances() -> None:
    """监控仓位按组合目标延续，不能错误展示为固定100%。"""
    calendar = list(pd.bdate_range("2024-01-31", "2024-02-05"))
    targets = {
        "20240131": {"A": 0.7, "GOLD": 0.15, "BOND": 0.15},
        "20240202": {"A": 0.21, "GOLD": 0.15, "BOND": 0.15},
    }

    exposure = build_effective_exposure_series(targets, calendar)

    assert exposure.loc[pd.Timestamp("2024-02-01")] == pytest.approx(1.0)
    assert exposure.loc[pd.Timestamp("2024-02-05")] == pytest.approx(0.51)
