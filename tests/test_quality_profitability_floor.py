"""Quality 盈利底线过滤与研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import quality_profitability_floor_feasibility_study as study
from strategies.quality_profitability_floor_signal import (
    apply_positive_profitability_floor,
    build_quality_profitability_floor_topn,
)


def test_positive_floor_requires_five_visible_reports() -> None:
    """盈利底线必须为正、连续五期且在信号日前可见。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 4,
            "symbol": ["A", "B", "C", "D"],
            "roa_floor_5y": [1.0, 0.0, 2.0, 3.0],
            "observations": [5, 5, 4, 5],
            "latest_publish_date": [
                "20230430",
                "20230430",
                "20230430",
                "20240201",
            ],
        }
    )

    filtered = apply_positive_profitability_floor(frame)

    assert filtered["symbol"].tolist() == ["A"]


def test_floor_topn_scores_full_cross_section_before_filter() -> None:
    """过滤器不得在缩小后的股票池内重算 Quality 标准化。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 3,
            "symbol": ["A", "B", "C"],
            "roe": [10.0, 9.0, 8.0],
            "roa": [8.0, 7.0, 6.0],
            "ocf_to_or": [0.3, 0.2, 0.1],
            "earnings_yield": [0.10, 0.08, 0.06],
            "book_yield": [0.20, 0.18, 0.16],
            "roa_floor_5y": [1.0, -1.0, 1.0],
            "observations": [5, 5, 5],
            "latest_publish_date": ["20230430"] * 3,
        }
    )

    _, holdings = build_quality_profitability_floor_topn(
        frame,
        study.EXPECTED_WEIGHTS,
        top_n=2,
    )

    assert holdings["symbol"].tolist() == ["A", "C"]
    assert holdings["factor_score"].nunique() == 2


def test_feasibility_rejects_trivial_filter() -> None:
    """持仓替换不足一成说明过滤器形同虚设，不应进入回测。"""
    merged = pd.DataFrame(
        {
            "signal_date": ["20220131"],
            "symbol": ["A"],
            "latest_publish_date": ["20210430"],
        }
    )
    monthly = pd.DataFrame(
        {
            "signal_date": ["20220131"],
            "floor_coverage": [0.9],
            "filtered_count": [100],
            "constructible": [True],
            "replacement_share": [0.05],
        }
    )

    result = study.evaluate_feasibility(merged, monthly, "20220131")

    assert result["passed"] is False
    assert result["checks"]["filter_is_not_trivial"] is False


def test_feasibility_accepts_exact_ten_percent_replacement() -> None:
    """二十只持仓替换两只应视为达到冻结的10%边界。"""
    merged = pd.DataFrame(
        {
            "signal_date": ["20220131"],
            "symbol": ["A"],
            "latest_publish_date": ["20210430"],
        }
    )
    monthly = pd.DataFrame(
        {
            "signal_date": ["20220131"],
            "floor_coverage": [0.9],
            "filtered_count": [100],
            "constructible": [True],
            "replacement_share": [0.09999999999999998],
        }
    )

    result = study.evaluate_feasibility(merged, monthly, "20220131")

    assert result["passed"] is True


def test_same_fingerprint_reuses_before_data_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同过滤语义和数据版本必须在大表扫描前复用。"""
    for path in [
        tmp_path / "fina_indicator.duckdb",
        tmp_path / "income.duckdb",
        tmp_path / "balancesheet.duckdb",
        tmp_path / "cashflow.duckdb",
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应扫描数据"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_formal_gate_requires_three_percent_drawdown_improvement() -> None:
    """风险过滤器若没有改善至少3个百分点回撤，就没有研究价值。"""
    from examples import quality_profitability_floor_study as formal

    candidate = {
        key: {
            "annualized_return": 0.12,
            "max_drawdown": -0.25,
            "sharpe": 0.70,
            "calmar": 0.48,
            "excess_return": 0.20,
            "annual_turnover": 4.0,
        }
        for key in [*formal.FOLDS, "full"]
    }
    delta = {
        "full_drawdown_improvement": 0.02,
        "early_drawdown_improvement": 0.04,
        "sharpe_change": 0.01,
        "annual_return_change": -0.01,
    }

    gate = formal.evaluate_gate(candidate, delta)

    assert gate["passed"] is False
    assert gate["checks"]["full_drawdown_improves_3pct"] is False


def test_formal_study_uses_grid_risk_layer() -> None:
    """候选与基线必须显式使用 GRID 风险层。"""
    from examples import quality_profitability_floor_study as formal

    assert formal.RESEARCH_SPEC.definition["risk_overlay"]["mode"] == "GRID"
