"""Quality Balanced Value 市值残差评分测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import examples.quality_balanced_value_size_residual_study as study
from runtime.paths import RuntimePaths


def _scores_and_size() -> tuple[pd.DataFrame, pd.DataFrame]:
    sizes = np.linspace(10.0, 20.0, 40)
    scores: list[dict[str, object]] = []
    market: list[dict[str, object]] = []
    for index, log_size in enumerate(sizes):
        symbol = f"S{index:02d}"
        independent = 2.0 if index % 7 == 0 else -0.1 * (index % 5)
        scores.append(
            {
                "signal_date": "20260130",
                "symbol": symbol,
                "name": symbol,
                "factor_score": 0.8 * log_size + independent,
            }
        )
        market.append(
            {
                "signal_date": "20260130",
                "symbol": symbol,
                "market_cap_proxy": float(np.exp(log_size)),
                "market_cap_percentile": index / 39,
            }
        )
    return pd.DataFrame(scores), pd.DataFrame(market)


def _period_metrics(turnover: float = 5.0) -> dict[str, dict[str, float]]:
    common = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": turnover,
    }
    return {
        "locked_test": {**common, "annualized_return": 0.08, "sharpe": 0.50},
        "full": common,
    }


def _residual(beta: float, passed: bool = True) -> dict[str, object]:
    return {"locked_beta": beta, "gate_passed": passed}


def test_cross_sectional_residual_removes_linear_size_component() -> None:
    scores, market = _scores_and_size()

    selections, holdings, diagnostics = study._build_selections(scores, market)

    assert len(selections[study.EXPERIMENT_ID]["20260130"]) == 20
    assert diagnostics["median_raw_score_size_correlation"] > 0.90
    assert abs(
        diagnostics["median_residual_score_size_correlation"]
    ) < 1e-10
    selected = holdings[holdings["strategy_id"].eq(study.EXPERIMENT_ID)]
    assert "size_residual_score" in selected.columns


def test_gate_requires_residual_and_realized_style_neutrality() -> None:
    gate = study.evaluate_gate(
        candidate=_period_metrics(),
        baseline=_period_metrics(turnover=6.0),
        stress={"annualized_return": 0.08, "sharpe": 0.60},
        candidate_residual=_residual(0.6),
        baseline_residual=_residual(1.0),
        residual_diagnostics={
            "market_cap_coverage": 1.0,
            "median_residual_score_size_correlation": 0.0,
        },
    )

    assert gate["passed"] is True
    assert gate["locked_style_beta_reduction"] == pytest.approx(0.4)


def test_gate_rejects_statistically_neutral_score_without_return_residual() -> None:
    gate = study.evaluate_gate(
        candidate=_period_metrics(),
        baseline=_period_metrics(turnover=6.0),
        stress={"annualized_return": 0.08, "sharpe": 0.60},
        candidate_residual=_residual(0.6, passed=False),
        baseline_residual=_residual(1.0),
        residual_diagnostics={
            "market_cap_coverage": 1.0,
            "median_residual_score_size_correlation": 0.0,
        },
    )

    assert gate["passed"] is False
    assert gate["checks"]["walk_forward_style_residual_gate_passed"] is False


def test_reused_attempt_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-residual-run"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(study, "_data_version", lambda paths: "test-data")
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not calculate")
        ),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260728")

    assert result["reused"] is True
