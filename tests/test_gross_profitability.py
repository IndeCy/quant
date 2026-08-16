"""Gross Profitability 因子研究测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import gross_profitability_study as study
from factors.gross_profitability import score_gross_profitability_frame


def test_gross_profitability_uses_margin_turnover_interaction() -> None:
    """相同毛利率下，更高资产周转率必须获得更高得分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW", "MARGIN_ONLY"],
            "grossprofit_margin": [30.0, 30.0, 60.0],
            "assets_turn": [2.0, 0.5, 0.2],
        }
    )

    result = score_gross_profitability_frame(frame).set_index("symbol")

    assert result.loc["HIGH", "gross_profitability"] == pytest.approx(60.0)
    assert result.loc["HIGH", "factor_score"] > result.loc["LOW", "factor_score"]
    assert (
        result.loc["LOW", "factor_score"]
        > result.loc["MARGIN_ONLY", "factor_score"]
    )


def test_universe_does_not_require_roa_or_cash_flow() -> None:
    """独立盈利能力因子股票池不能暗中依赖Quality核心因子。"""
    base = {
        "signal_date": "20240531",
        "name": "正常公司",
        "list_date": "20100101",
        "delist_date": None,
        "st_name": None,
        "end_date": "20231231",
        "f_ann_date": "20240430",
        "grossprofit_margin": 30.0,
        "assets_turn": 1.0,
        "roa": None,
        "ocf_to_or": None,
    }
    frame = pd.DataFrame(
        [
            {**base, "symbol": "KEEP"},
            {**base, "symbol": "ST", "name": "*ST公司"},
            {**base, "symbol": "NEW", "list_date": "20230101"},
        ]
    )

    result = study.apply_gross_profitability_universe(frame)

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
