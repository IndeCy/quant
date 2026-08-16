"""低资产增长投资因子测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import low_asset_growth_study as study
from factors.asset_growth import score_low_asset_growth_frame


def test_asset_growth_factor_prefers_conservative_investment() -> None:
    """资产增长越低，投资因子得分必须越高。"""
    frame = pd.DataFrame(
        {
            "symbol": ["SHRINK", "STEADY", "AGGRESSIVE"],
            "assets_yoy": [-5.0, 8.0, 40.0],
        }
    )

    result = score_low_asset_growth_frame(frame).set_index("symbol")

    assert result.loc["SHRINK", "factor_score"] > result.loc["STEADY", "factor_score"]
    assert (
        result.loc["STEADY", "factor_score"]
        > result.loc["AGGRESSIVE", "factor_score"]
    )


def test_asset_growth_universe_does_not_require_quality_metrics() -> None:
    """独立投资因子股票池不能暗中要求ROE、ROA或OCF。"""
    base = {
        "signal_date": "20240531",
        "name": "正常公司",
        "list_date": "20100101",
        "delist_date": None,
        "st_name": None,
        "end_date": "20231231",
        "f_ann_date": "20240430",
        "assets_yoy": 5.0,
        "roe": None,
        "roa": None,
        "ocf_to_or": None,
    }
    frame = pd.DataFrame(
        [
            {**base, "symbol": "KEEP"},
            {**base, "symbol": "ST", "name": "ST公司"},
            {**base, "symbol": "NEW", "list_date": "20230101"},
        ]
    )

    result = study.apply_asset_growth_universe(frame)

    assert result["symbol"].tolist() == ["KEEP"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同财务、行情版本和定义不得重复回测。"""
    for filename in [
        "daily_adj_19901219_20260615.duckdb",
        "fina_indicator.duckdb",
        "income.duckdb",
        "balancesheet.duckdb",
        "cashflow.duckdb",
    ]:
        (tmp_path / filename).write_bytes(filename.encode())
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True
