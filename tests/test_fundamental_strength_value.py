"""基本面强度价值策略研究测试。"""

from __future__ import annotations

import pandas as pd

import examples.fundamental_strength_value_study as study
from factors.fundamental_strength_value import score_fundamental_strength_value_frame
from runtime.paths import RuntimePaths


def _candidate(symbol: str, **overrides: float) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": symbol,
        "roa": 5.0,
        "ocf_to_or": 0.1,
        "ocf_to_profit": 1.2,
        "netprofit_yoy": 10.0,
        "debt_to_assets": 40.0,
        "grossprofit_margin": 30.0,
        "assets_turn": 0.8,
        "earnings_yield": 0.08,
        "book_yield": 0.5,
    }
    row.update(overrides)
    return row


def test_strength_value_score_rewards_cash_backed_healthy_company() -> None:
    """健康且便宜的公司应排在弱基本面公司之前。"""
    frame = pd.DataFrame(
        [
            _candidate("HEALTHY"),
            _candidate(
                "WEAK",
                roa=-2.0,
                ocf_to_or=-0.1,
                ocf_to_profit=0.4,
                netprofit_yoy=-20.0,
                debt_to_assets=80.0,
                grossprofit_margin=10.0,
                assets_turn=0.2,
                earnings_yield=0.02,
                book_yield=0.1,
            ),
        ]
    )

    result = score_fundamental_strength_value_frame(frame)

    assert result.iloc[0]["symbol"] == "HEALTHY"
    assert result.iloc[0]["fundamental_strength"] == 1.0
    assert result.iloc[1]["fundamental_strength"] == 0.0


def test_strength_only_and_value_only_are_distinct_diagnostics() -> None:
    """单腿归因必须产生不同排序，不能退化成同一分数。"""
    frame = pd.DataFrame(
        [
            _candidate("STRONG_EXPENSIVE", earnings_yield=0.01, book_yield=0.05),
            _candidate(
                "WEAK_CHEAP",
                roa=-1.0,
                ocf_to_or=-0.1,
                ocf_to_profit=0.5,
                netprofit_yoy=-5.0,
                debt_to_assets=90.0,
                grossprofit_margin=5.0,
                assets_turn=0.1,
                earnings_yield=0.15,
                book_yield=1.0,
            ),
        ]
    )

    strength = score_fundamental_strength_value_frame(frame, value_weight=0.0)
    value = score_fundamental_strength_value_frame(frame, value_weight=1.0)

    assert strength.iloc[0]["symbol"] == "STRONG_EXPENSIVE"
    assert value.iloc[0]["symbol"] == "WEAK_CHEAP"


def test_reused_research_does_not_open_large_dataset(monkeypatch, tmp_path) -> None:
    """命中相同研究指纹时必须在行情和财务计算前返回。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-run"}

    monkeypatch.setattr(study, "begin_research_attempt", lambda *args, **kwargs: ReusedAttempt())
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not calculate")),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
    assert result["run_fingerprint"] == "same-run"
