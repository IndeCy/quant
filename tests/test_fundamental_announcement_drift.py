"""季度公告后基本面漂移因子与研究门禁测试。"""

from __future__ import annotations

import pandas as pd

import examples.fundamental_announcement_drift_study as study
from factors.fundamental_announcement_drift import (
    score_fundamental_announcement_drift_frame,
)
from runtime.paths import RuntimePaths


def _sample_frame() -> pd.DataFrame:
    """构造增长、现金质量和公告时效不同的最小样本。"""
    return pd.DataFrame(
        [
            {
                "symbol": "STRONG",
                "signal_date": "20260630",
                "f_ann_date": "20260430",
                "roa": 8.0,
                "ocf_to_or": 0.20,
                "netprofit_yoy": 40.0,
                "tr_yoy": 25.0,
            },
            {
                "symbol": "WEAK",
                "signal_date": "20260630",
                "f_ann_date": "20260430",
                "roa": 5.0,
                "ocf_to_or": 0.05,
                "netprofit_yoy": 10.0,
                "tr_yoy": 8.0,
            },
            {
                "symbol": "BAD_CASH",
                "signal_date": "20260630",
                "f_ann_date": "20260430",
                "roa": 6.0,
                "ocf_to_or": -0.10,
                "netprofit_yoy": 30.0,
                "tr_yoy": 20.0,
            },
            {
                "symbol": "STALE",
                "signal_date": "20260630",
                "f_ann_date": "20260301",
                "roa": 7.0,
                "ocf_to_or": 0.10,
                "netprofit_yoy": 30.0,
                "tr_yoy": 20.0,
            },
        ]
    )


def test_main_factor_filters_stale_and_negative_cash() -> None:
    """主策略必须同时满足公告时效和现金质量。"""
    result = score_fundamental_announcement_drift_frame(_sample_frame())

    assert result["symbol"].tolist() == ["STRONG", "WEAK"]


def test_stronger_synchronized_growth_ranks_first() -> None:
    """收入、利润和现金质量同步更强的股票应排名更高。"""
    result = score_fundamental_announcement_drift_frame(_sample_frame())

    assert result.iloc[0]["symbol"] == "STRONG"
    assert result.iloc[0]["factor_score"] > result.iloc[1]["factor_score"]


def test_growth_diagnostic_does_not_require_cash_gate() -> None:
    """增长单腿对照允许现金转化为负，但仍拦截过期公告。"""
    result = score_fundamental_announcement_drift_frame(
        _sample_frame(),
        require_cash_quality=False,
    )

    assert set(result["symbol"]) == {"STRONG", "WEAK", "BAD_CASH"}
    assert "STALE" not in set(result["symbol"])


def test_reused_announcement_study_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    """相同指纹必须在物化季度财务快照前复用。"""
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-announcement-run"}

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
    assert result["run_fingerprint"] == "same-announcement-run"
