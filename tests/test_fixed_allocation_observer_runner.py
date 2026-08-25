from __future__ import annotations

from runtime.strategy_batch_runner import build_default_strategy_executor_registry
from strategies.fixed_allocation_observer_runner import validate_fixed_assets


def _instance() -> dict[str, object]:
    return {
        "strategy_id": "global_defensive_equal_v1",
        "name": "全球防守三资产等权 V1",
        "template_id": "fixed_allocation_observer",
        "construction": {
            "assets": [
                {"symbol": "513500.SH", "weight": 1 / 3},
                {"symbol": "518880.SH", "weight": 1 / 3},
                {"symbol": "511010.SH", "weight": 1 / 3},
            ]
        },
        "config": {"trade_policy": "observation_only"},
    }


def test_fixed_assets_are_unique_positive_and_fully_invested() -> None:
    assert validate_fixed_assets(_instance()) == {
        "513500.SH": 1 / 3,
        "518880.SH": 1 / 3,
        "511010.SH": 1 / 3,
    }


def test_fixed_allocation_observer_has_dedicated_executor() -> None:
    registry = build_default_strategy_executor_registry()
    assert registry.resolve_id(_instance()) == "fixed_allocation_observer"
