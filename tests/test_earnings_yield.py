"""点时盈利收益率评分与数据门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import earnings_yield_feasibility_study as study
from examples import earnings_yield_feasibility_v2_study as study_v2
from factors.earnings_yield import score_earnings_yield


def test_score_prefers_high_positive_earnings_yield() -> None:
    """高正 E/P 应得高分，负盈利必须排除。"""
    frame = pd.DataFrame(
        {
            "symbol": ["CHEAP", "EXPENSIVE", "LOSS"],
            "earnings_yield": [0.12, 0.03, -0.10],
        }
    )

    scored = score_earnings_yield(frame).set_index("symbol")

    assert set(scored.index) == {"CHEAP", "EXPENSIVE"}
    assert scored.loc["CHEAP", "factor_score"] > scored.loc[
        "EXPENSIVE",
        "factor_score",
    ]


def test_feasibility_reuses_same_fingerprint_without_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义与数据版本必须复用。"""
    for path in [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "fina_indicator.duckdb",
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "cashflow.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "experiment_id": study.EXPERIMENT_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新扫描"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_v2_adjustment_missing_share_uses_investable_denominator() -> None:
    """不满足上市年限的记录不能抬高标准股票池复权缺失率。"""
    source = pd.DataFrame(
        [
            {
                "signal_date": "20240131",
                "symbol": "ELIGIBLE",
                "name": "合格公司",
                "list_date": "20100101",
                "delist_date": None,
                "st_name": None,
                "end_date": "20221231",
                "f_ann_date": "20230331",
                "eps": 1.0,
                "raw_close": 10.0,
                "current_adj_factor": 1.0,
                "report_adj_factor": 1.0,
                "roa": 0.1,
                "vol60": 0.2,
                "ret120": 0.1,
                "amount20": 100_000.0,
            },
            {
                "signal_date": "20240131",
                "symbol": "NEW_LISTING",
                "name": "新股公司",
                "list_date": "20230101",
                "delist_date": None,
                "st_name": None,
                "end_date": "20221231",
                "f_ann_date": "20230331",
                "eps": 1.0,
                "raw_close": 10.0,
                "current_adj_factor": None,
                "report_adj_factor": None,
                "roa": 0.1,
                "vol60": 0.2,
                "ret120": 0.1,
                "amount20": 100_000.0,
            },
        ]
    )

    accepted, diagnostics = study_v2.build_investable_candidates(source)

    assert accepted["symbol"].tolist() == ["ELIGIBLE"]
    assert diagnostics["eligible_source_rows"] == 1
    assert diagnostics["adjustment_missing_share"] == 0


def test_v2_feasibility_reuses_same_fingerprint_without_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """V2 相同语义与数据版本也必须在扫描前复用。"""
    for path in [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "fina_indicator.duckdb",
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "cashflow.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "experiment_id": study_v2.EXPERIMENT_ID}

    monkeypatch.setattr(
        study_v2,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study_v2,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("V2 不应重新扫描"),
    )

    result = study_v2.run_study(study_v2.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
