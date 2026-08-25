"""Quality防御组合资金可行性研究测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from examples import quality_defensive_assets_capital_feasibility_study as study
from runtime.paths import RuntimePaths


def test_run_study_reuses_same_fingerprint_before_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """命中历史研究时不得重新加载财务大表或启动Paper情景。"""

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


def test_build_execution_market_applies_gap_to_raw_close() -> None:
    """次日压力情景只改变执行日原始价格，不修改标的和成交量。"""
    signal = pd.DataFrame(
        [
            {
                "trade_date": "20260723",
                "symbol": "000001.SZ",
                "open": 9.8,
                "high": 10.1,
                "low": 9.7,
                "close": 10.0,
                "volume": 100_000,
                "amount": 1_000_000,
                "is_suspended": False,
                "limit_up": False,
                "limit_down": False,
            }
        ]
    )

    execution = study.build_execution_market(signal, "20260724", 0.02)

    assert execution.iloc[0]["trade_date"] == "20260724"
    assert execution.iloc[0]["open"] == pytest.approx(10.2)
    assert execution.iloc[0]["close"] == pytest.approx(10.2)
    assert execution.iloc[0]["volume"] == 100_000


def test_evaluate_capital_cases_requires_zero_rejection_and_low_drift() -> None:
    """50万或100万在2%高开下失败时不得进入长期观察。"""
    cases = [
        {
            "scenario": "flat_open",
            "capital": 500_000.0,
            "rejected_orders": 0,
            "tracking_total_variation": 0.02,
        },
        {
            "scenario": "gap_up_2pct",
            "capital": 500_000.0,
            "rejected_orders": 1,
            "tracking_total_variation": 0.06,
        },
        {
            "scenario": "gap_up_2pct",
            "capital": 1_000_000.0,
            "rejected_orders": 0,
            "tracking_total_variation": 0.03,
        },
    ]

    result = study.evaluate_capital_cases(cases)

    assert result["research_outcome"] == "REQUIRES_ENGINE_FIX"
    assert result["minimum_capital_flat_open"] == 500_000.0
    assert result["minimum_capital_gap_up_2pct"] == 1_000_000.0
