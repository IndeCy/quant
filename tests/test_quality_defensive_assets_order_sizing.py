"""Quality防御组合T+1订单数量规划研究测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from backtest.paper_execution import BrokerConfig
from examples import quality_defensive_assets_order_sizing_study as study
from runtime.paths import RuntimePaths


def test_run_study_reuses_fingerprint_before_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """同一研究指纹命中后不得重新读取大表或启动撮合。"""

    @dataclass
    class ReusedAttempt:
        should_run: bool = False

        def cached_result(self):
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重复计算"),
    )

    result = study.run_study(
        RuntimePaths(tmp_path / "runtime"),
        "20260723",
    )

    assert result == {"reused": True}


def test_open_aware_weights_fit_gap_price_and_fees() -> None:
    """T+1重算必须按开盘、滑点、佣金和整手控制总占用资金。"""
    signal = _market(10.0)
    execution = _market(10.5)
    config = BrokerConfig(
        slippage_bps=10.0,
        commission_rate=0.0003,
        min_commission=5.0,
        lot_size=100,
    )

    weights = study.build_open_aware_order_weights(
        {"AAA.SZ": 0.5, "BBB.SZ": 0.5},
        signal,
        execution,
        100_000.0,
        config,
    )
    signal_prices = {"AAA.SZ": 10.0, "BBB.SZ": 10.0}
    quantities = {
        symbol: int(100_000.0 * weight / signal_prices[symbol])
        // 100
        * 100
        for symbol, weight in weights.items()
    }
    costs = study.estimate_buy_cost(
        quantities,
        {"AAA.SZ": 10.5, "BBB.SZ": 10.5},
        config,
    )

    assert costs <= 100_000.0
    assert quantities == {"AAA.SZ": 4_700, "BBB.SZ": 4_700}


def test_policy_evaluation_prefers_zero_rejection_and_low_drift() -> None:
    """排序必须先避免拒单，再比较组合偏离，不能按收益反向挑政策。"""
    cases = []
    for capital in (500_000.0, 1_000_000.0):
        cases.extend(
            [
                _case(
                    "close_sized_current",
                    capital,
                    rejected=1,
                    drift=0.04,
                    max_gap=0.035,
                ),
                _case(
                    "close_sized_cash_reserve_5pct",
                    capital,
                    rejected=0,
                    drift=0.05,
                    max_gap=0.01,
                ),
                _case(
                    "open_aware_resized",
                    capital,
                    rejected=0,
                    drift=0.01,
                    max_gap=0.005,
                ),
            ]
        )

    result = study.evaluate_order_policies(cases)

    assert result["recommended_policy"] == "open_aware_resized"
    assert (
        result["research_outcome"]
        == "OPEN_AWARE_ORDER_SIZING_RECOMMENDED"
    )


def _market(price: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "AAA.SZ", "open": price, "close": price},
            {"symbol": "BBB.SZ", "open": price, "close": price},
        ]
    )


def _case(
    policy: str,
    capital: float,
    *,
    rejected: int,
    drift: float,
    max_gap: float,
) -> dict[str, float | str | int]:
    return {
        "order_policy": policy,
        "capital": capital,
        "rejected_orders": rejected,
        "tracking_total_variation": drift,
        "max_abs_weight_gap": max_gap,
        "gross_exposure": 1.0 - drift,
        "execution_cost": 100.0,
    }
