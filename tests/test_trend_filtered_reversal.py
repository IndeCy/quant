"""趋势过滤短期反转因子与研究指纹测试。"""

from __future__ import annotations

import pandas as pd

import examples.trend_filtered_reversal_study as study
from factors.trend_filtered_reversal import score_trend_filtered_reversal_frame
from runtime.paths import RuntimePaths


def _sample_frame() -> pd.DataFrame:
    """构造包含有效回撤、崩盘和趋势破坏的最小横截面。"""
    return pd.DataFrame(
        [
            {
                "symbol": "DEEP",
                "ret20": -0.15,
                "ret120": 0.20,
                "close": 12.0,
                "ma60": 11.5,
                "ma120": 10.0,
            },
            {
                "symbol": "SHALLOW",
                "ret20": -0.05,
                "ret120": 0.15,
                "close": 11.0,
                "ma60": 10.5,
                "ma120": 10.0,
            },
            {
                "symbol": "CRASH",
                "ret20": -0.30,
                "ret120": 0.10,
                "close": 11.0,
                "ma60": 10.5,
                "ma120": 10.0,
            },
            {
                "symbol": "BROKEN",
                "ret20": -0.10,
                "ret120": -0.05,
                "close": 8.0,
                "ma60": 9.0,
                "ma120": 10.0,
            },
        ]
    )


def test_trend_reversal_filters_crash_and_broken_trend() -> None:
    """主策略只保留长期趋势未破坏的温和回撤。"""
    result = score_trend_filtered_reversal_frame(_sample_frame())

    assert result["symbol"].tolist() == ["DEEP", "SHALLOW"]


def test_deeper_valid_pullback_receives_higher_score() -> None:
    """在同一健康趋势内，更深但非崩盘的回撤应优先。"""
    result = score_trend_filtered_reversal_frame(_sample_frame())

    assert result.iloc[0]["symbol"] == "DEEP"
    assert result.iloc[0]["factor_score"] > result.iloc[1]["factor_score"]


def test_unfiltered_diagnostic_keeps_broken_trend() -> None:
    """归因对照关闭趋势门禁，但仍拦截超过20%的崩盘样本。"""
    result = score_trend_filtered_reversal_frame(
        _sample_frame(),
        require_positive_trend=False,
    )

    assert set(result["symbol"]) == {"DEEP", "SHALLOW", "BROKEN"}
    assert "CRASH" not in set(result["symbol"])


def test_reused_study_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    """相同运行指纹必须在加载全A行情前直接复用。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-reversal-run"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("must not calculate")),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260723")

    assert result["reused"] is True
    assert result["run_fingerprint"] == "same-reversal-run"
