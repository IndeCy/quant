"""防御动量因子与研究门禁测试。"""

from __future__ import annotations

import pandas as pd

import examples.defensive_momentum_study as study
from factors.defensive_momentum import score_defensive_momentum_frame
from runtime.paths import RuntimePaths


def test_skip_month_momentum_avoids_recent_spike() -> None:
    """中期持续上涨应优于全部涨幅只发生在近20日的股票。"""
    frame = pd.DataFrame(
        [
            {"symbol": "STEADY", "ret120": 0.30, "ret20": 0.02, "vol60": 0.01},
            {"symbol": "SPIKE", "ret120": 0.35, "ret20": 0.30, "vol60": 0.03},
        ]
    )

    result = score_defensive_momentum_frame(frame, momentum_weight=1.0)

    assert result.iloc[0]["symbol"] == "STEADY"
    assert result.iloc[0]["momentum_skip_20d"] > result.iloc[1]["momentum_skip_20d"]


def test_defensive_blend_rewards_lower_volatility_at_equal_momentum() -> None:
    """动量相同时，低波股票应获得更高综合分。"""
    frame = pd.DataFrame(
        [
            {"symbol": "LOW_VOL", "ret120": 0.30, "ret20": 0.05, "vol60": 0.01},
            {"symbol": "HIGH_VOL", "ret120": 0.30, "ret20": 0.05, "vol60": 0.05},
        ]
    )

    result = score_defensive_momentum_frame(frame)

    assert result.iloc[0]["symbol"] == "LOW_VOL"


def test_reused_defensive_study_skips_calculation(monkeypatch, tmp_path) -> None:
    """相同运行指纹必须在全A数据加载前复用。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-defensive-run"}

    monkeypatch.setattr(study, "begin_research_attempt", lambda *args, **kwargs: ReusedAttempt())
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not calculate")),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
    assert result["run_fingerprint"] == "same-defensive-run"
