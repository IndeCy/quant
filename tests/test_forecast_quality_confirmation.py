"""业绩预告与 Quality 确认评分及研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from examples import forecast_quality_feasibility_study as study
from factors.forecast_quality_confirmation import (
    score_forecast_quality_confirmation,
)


def test_equal_rank_blend_requires_both_inputs() -> None:
    """组合分数必须由预告和 Quality 横截面秩等权产生。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "forecast_score": [3.0, 2.0, 1.0],
            "quality_score": [1.0, 3.0, 2.0],
        }
    )

    scored = score_forecast_quality_confirmation(frame).set_index("symbol")

    assert scored.loc["B", "factor_score"] > scored.loc["A", "factor_score"]
    assert scored.loc["A", "factor_score"] > scored.loc["C", "factor_score"]
    assert scored.loc["B", "factor_score"] == pytest.approx(5.0 / 6.0)


def test_feasibility_rejects_insufficient_locked_coverage() -> None:
    """锁定期不足九成月份可构造 Top40 时必须停止。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131"],
            "symbol": ["A", "B"],
            "publish_date": ["20211201", "20220101"],
            "f_ann_date": ["20210430", "20210430"],
            "factor_score": [0.8, 0.9],
        }
    )
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131"],
            "candidate_count": [40, 39],
            "unique_score_count": [40, 39],
            "top40_constructible": [True, False],
            "top40_median_adv_rmb": [30_000_000.0, 30_000_000.0],
            "forecast_quality_spearman": [0.1, 0.1],
        }
    )

    result = study.evaluate_feasibility(candidates, monthly, "20220131")

    assert result["passed"] is False
    assert result["checks"]["locked_top40_constructible_share"] is False


def test_feasibility_reuses_same_fingerprint_without_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同组合语义和数据版本必须在扫描前复用。"""
    for path in [
        tmp_path / "forecast.duckdb",
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


def test_confirmation_gate_requires_forecast_risk_improvement() -> None:
    """确认层必须实质改善预告单腿回撤，不能只靠绝对收益晋级。"""
    from examples import forecast_quality_confirmation_study as confirmation

    candidate = {
        key: {
            "annualized_return": 0.12,
            "max_drawdown": -0.25,
            "sharpe": 0.70,
            "excess_return": 0.20,
            "annual_turnover": 4.0,
        }
        for key in [*confirmation.FOLDS, "full"]
    }
    delta = {
        "drawdown_improvement": 0.09,
        "sharpe_change": 0.10,
        "annual_return_change": -0.01,
    }

    gate = confirmation.evaluate_gate(candidate, delta)

    assert gate["passed"] is False
    assert gate["checks"]["forecast_drawdown_improves_10pct"] is False


def test_confirmation_uses_grid_risk_layer() -> None:
    """正式研究必须显式使用 GRID，避免 FIXED 静默变成满仓。"""
    from examples import forecast_quality_confirmation_study as confirmation

    assert confirmation.RESEARCH_SPEC.definition["risk_overlay"]["mode"] == "GRID"
