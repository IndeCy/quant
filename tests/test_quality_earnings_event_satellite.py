"""Quality慢核心与SUE事件卫星组合测试。"""

from __future__ import annotations

import examples.quality_earnings_event_satellite_study as study
from runtime.paths import RuntimePaths


def test_combined_targets_carry_event_and_sum_overlap_weights() -> None:
    quality = {
        "20260130": {"A": 0.5, "B": 0.5},
        "20260227": {"A": 0.5, "C": 0.5},
    }
    event = {
        "20260130": {"A": 0.5, "D": 0.5},
    }

    combined, diagnostics = study.build_combined_targets(
        ["20260130", "20260227"],
        quality,
        event,
    )

    assert combined["20260130"] == {
        "A": 0.5,
        "B": 0.4,
        "D": 0.1,
    }
    assert combined["20260227"] == {
        # Quality 0.4，加上沿用事件目标中的0.1。
        "A": 0.5,
        "C": 0.4,
        "D": 0.1,
    }
    assert diagnostics["event_active_share"] == 1.0


def test_before_first_event_target_portfolio_is_full_quality() -> None:
    combined, diagnostics = study.build_combined_targets(
        ["20260130", "20260227"],
        {
            "20260130": {"A": 0.5, "B": 0.5},
            "20260227": {"A": 0.5, "C": 0.5},
        },
        {"20260227": {"D": 1.0}},
    )

    assert combined["20260130"] == {"A": 0.5, "B": 0.5}
    assert sum(combined["20260227"].values()) == 1.0
    assert diagnostics["event_active_months"] == 1.0


def _metrics(
    *,
    full_return: float,
    full_sharpe: float,
    full_drawdown: float,
    locked_return: float,
    locked_sharpe: float,
    locked_drawdown: float,
    turnover: float,
) -> dict[str, dict[str, float]]:
    return {
        "full": {
            "annualized_return": full_return,
            "sharpe": full_sharpe,
            "max_drawdown": full_drawdown,
            "annual_turnover": turnover,
        },
        "locked_test": {
            "annualized_return": locked_return,
            "sharpe": locked_sharpe,
            "max_drawdown": locked_drawdown,
            "annual_turnover": turnover,
        },
    }


def test_gate_requires_satellite_to_improve_locked_core() -> None:
    core = _metrics(
        full_return=0.10,
        full_sharpe=0.60,
        full_drawdown=-0.20,
        locked_return=0.07,
        locked_sharpe=0.45,
        locked_drawdown=-0.20,
        turnover=6.0,
    )
    combined = _metrics(
        full_return=0.10,
        full_sharpe=0.65,
        full_drawdown=-0.21,
        locked_return=0.08,
        locked_sharpe=0.50,
        locked_drawdown=-0.21,
        turnover=7.0,
    )

    gate = study.evaluate_gate(
        combined=combined,
        core=core,
        stress={"annualized_return": 0.10, "sharpe": 0.60},
        combined_residual={"gate_passed": True},
        event_core_correlation=0.60,
    )

    assert gate["passed"] is True


def test_reused_attempt_skips_heavy_calculation(monkeypatch, tmp_path) -> None:
    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True, "run_fingerprint": "same-event-run"}

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
