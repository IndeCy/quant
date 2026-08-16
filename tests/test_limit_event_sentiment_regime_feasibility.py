from __future__ import annotations

from examples import limit_event_sentiment_regime_feasibility_study as study


def test_definition_uses_natural_signed_event_ratio_without_returns() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["outcome_returns_loaded"] is False
    assert definition["daily_score"] == "(limit_up_count-limit_down_count)/(up+down)"
    assert definition["smoothing"] == "trailing_5_trading_day_mean"
