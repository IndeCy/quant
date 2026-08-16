"""Quality Balanced Value 缓冲调仓研究测试。"""

from __future__ import annotations

import pandas as pd

import examples.quality_balanced_value_buffered_study as study
from runtime.paths import RuntimePaths


def _scores() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    first = [f"S{index:02d}" for index in range(30)]
    second = [*first[20:30], *first[:20]]
    for signal_date, symbols in [
        ("20260130", first),
        ("20260227", second),
    ]:
        for rank, symbol in enumerate(symbols):
            rows.append(
                {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "name": symbol,
                    "factor_score": float(100 - rank),
                }
            )
    return pd.DataFrame(rows)


def _metrics(
    *,
    full_turnover: float,
    full_return: float = 0.12,
    locked_return: float = 0.10,
) -> dict[str, dict[str, float]]:
    common = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": full_turnover,
        "trade_count": 100.0,
        "execution_cost_impact": 0.02,
    }
    return {
        "2015_2017": {**common, "annualized_return": 0.10},
        "2018_2020": {**common, "annualized_return": 0.10},
        "2021_2023": {**common, "annualized_return": 0.10},
        "locked_test": {**common, "annualized_return": locked_return},
        "full": {**common, "annualized_return": full_return},
    }


def test_buffer_keeps_existing_holdings_inside_exit_rank() -> None:
    selections, _ = study._build_selections(_scores())

    baseline = selections[study.BASELINE_ID]["20260227"]
    buffered = selections[study.EXPERIMENT_ID]["20260227"]

    assert set(baseline) != set(buffered)
    assert set(buffered) == {f"S{index:02d}" for index in range(20)}


def test_gate_accepts_large_turnover_reduction_without_alpha_drag() -> None:
    gate = study.evaluate_gate(
        buffered=_metrics(full_turnover=4.0),
        baseline=_metrics(full_turnover=8.0, full_return=0.125, locked_return=0.105),
        stress={
            "annualized_return": 0.10,
            "max_drawdown": -0.22,
            "sharpe": 0.60,
        },
        turnover={
            f"{study.EXPERIMENT_ID}_median_replacement_share": 0.20,
        },
    )

    assert gate["passed"] is True
    assert gate["checks"]["turnover_reduced_by_at_least_30pct"] is True


def test_gate_rejects_buffer_that_does_not_reduce_turnover() -> None:
    gate = study.evaluate_gate(
        buffered=_metrics(full_turnover=7.0),
        baseline=_metrics(full_turnover=8.0),
        stress={
            "annualized_return": 0.10,
            "max_drawdown": -0.22,
            "sharpe": 0.60,
        },
        turnover={
            f"{study.EXPERIMENT_ID}_median_replacement_share": 0.20,
        },
    )

    assert gate["passed"] is False
    assert gate["checks"]["turnover_reduced_by_at_least_30pct"] is False


def test_reused_attempt_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-buffered-run"}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_data_version",
        lambda paths: "test-data",
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not calculate")
        ),
    )

    result = study.run_study(RuntimePaths(tmp_path), "20260728")

    assert result["reused"] is True
    assert result["run_fingerprint"] == "same-buffered-run"
