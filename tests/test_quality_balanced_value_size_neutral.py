"""Quality Balanced Value 市值分层组合测试。"""

from __future__ import annotations

import pandas as pd

import examples.quality_balanced_value_size_neutral_study as study
from runtime.paths import RuntimePaths


def _scores_and_size() -> tuple[pd.DataFrame, pd.DataFrame]:
    scores: list[dict[str, object]] = []
    sizes: list[dict[str, object]] = []
    for index in range(40):
        symbol = f"S{index:02d}"
        scores.append(
            {
                "signal_date": "20260130",
                "symbol": symbol,
                "name": symbol,
                "factor_score": float(100 - index),
            }
        )
        sizes.append(
            {
                "signal_date": "20260130",
                "symbol": symbol,
                "market_cap_proxy": float(index + 1),
                "market_cap_percentile": index / 39,
            }
        )
    return pd.DataFrame(scores), pd.DataFrame(sizes)


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
    return {
        "locked_beta": beta,
        "gate_passed": passed,
    }


def test_size_neutral_selection_takes_five_from_each_quartile() -> None:
    scores, sizes = _scores_and_size()

    selections, holdings, diagnostics = study._build_selections(scores, sizes)

    selected = holdings[
        holdings["strategy_id"].eq(study.EXPERIMENT_ID)
    ]
    assert len(selections[study.EXPERIMENT_ID]["20260130"]) == 20
    assert selected.groupby("size_bucket").size().to_dict() == {
        0: 5,
        1: 5,
        2: 5,
        3: 5,
    }
    assert diagnostics["complete_bucket_month_share"] == 1.0


def test_gate_requires_real_style_beta_reduction() -> None:
    gate = study.evaluate_gate(
        candidate=_period_metrics(),
        baseline=_period_metrics(turnover=6.0),
        stress={"annualized_return": 0.08, "sharpe": 0.60},
        candidate_residual=_residual(0.6),
        baseline_residual=_residual(1.0),
        size_diagnostics={
            "market_cap_coverage": 1.0,
            "complete_bucket_month_share": 1.0,
        },
    )

    assert gate["passed"] is True
    assert gate["locked_style_beta_reduction"] == 0.4


def test_gate_rejects_nominal_buckets_without_style_reduction() -> None:
    gate = study.evaluate_gate(
        candidate=_period_metrics(),
        baseline=_period_metrics(turnover=6.0),
        stress={"annualized_return": 0.08, "sharpe": 0.60},
        candidate_residual=_residual(0.9),
        baseline_residual=_residual(1.0),
        size_diagnostics={
            "market_cap_coverage": 1.0,
            "complete_bucket_month_share": 1.0,
        },
    )

    assert gate["passed"] is False
    assert (
        gate["checks"]["locked_style_beta_reduced_by_at_least_30pct"]
        is False
    )


def test_reused_attempt_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-size-run"}

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
