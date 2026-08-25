"""五只科技ETF反转数据门禁测试。"""

from examples import a_share_tech_etf_weekly_reversal_feasibility_study as study


def test_definition_is_feasibility_only_and_uses_five_day_signal() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["signal_preview"]["formula"] == "close_t/close_t_minus_5-1"
    assert definition["signal_preview"]["future_holding_return_loaded"] is False
    assert definition["decision"] == "feasibility_only_no_return_backtest"


def test_universe_matches_frozen_tech_pool() -> None:
    assert set(study.RESEARCH_SPEC.definition["universe"]) == set(
        study.tech.TECH_SYMBOLS
    )
