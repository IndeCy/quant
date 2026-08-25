"""公告漂移缓冲组合与研究指纹测试。"""

from __future__ import annotations

import pandas as pd
import pytest

import examples.fundamental_announcement_drift_buffered_study as study
from portfolio.topn import build_buffered_topn_selections
from runtime.paths import RuntimePaths


def test_buffer_retains_existing_holding_inside_exit_band() -> None:
    """旧持仓仍在Top80时，即使跌出Top40也应保留。"""
    first = [
        {"signal_date": "20260130", "symbol": f"S{i:03d}", "score": 100 - i}
        for i in range(100)
    ]
    second_order = [*range(40, 80), *range(0, 40), *range(80, 100)]
    second = [
        {
            "signal_date": "20260227",
            "symbol": f"S{symbol:03d}",
            "score": 100 - rank,
        }
        for rank, symbol in enumerate(second_order)
    ]

    selections, _ = build_buffered_topn_selections(
        pd.DataFrame([*first, *second]),
        "score",
        40,
        80,
    )

    assert set(selections["20260227"]) == {f"S{i:03d}" for i in range(40)}


def test_buffer_replaces_holding_outside_exit_band() -> None:
    """旧持仓跌出Top80后必须被当前高排名股票替换。"""
    first = [
        {"signal_date": "20260130", "symbol": f"S{i:03d}", "score": 100 - i}
        for i in range(140)
    ]
    second_order = [*range(40, 140), *range(0, 40)]
    second = [
        {
            "signal_date": "20260227",
            "symbol": f"S{symbol:03d}",
            "score": 100 - rank,
        }
        for rank, symbol in enumerate(second_order)
    ]

    selections, _ = build_buffered_topn_selections(
        pd.DataFrame([*first, *second]),
        "score",
        40,
        80,
    )

    assert set(selections["20260227"]) == {f"S{i:03d}" for i in range(40, 80)}


def test_buffer_rejects_exit_rank_smaller_than_entry_rank() -> None:
    """退出排名不能比进入排名更窄。"""
    with pytest.raises(ValueError, match="exit_rank"):
        build_buffered_topn_selections(
            pd.DataFrame(columns=["signal_date", "symbol", "score"]),
            "score",
            40,
            20,
        )


def test_reused_buffered_study_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    """相同V2指纹必须在季度财务加载前复用。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-buffer-run"}

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
    assert result["run_fingerprint"] == "same-buffer-run"
