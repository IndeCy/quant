from __future__ import annotations

import pandas as pd

from examples import limit_down_weekly_reversal_feasibility_study as study


def test_definition_forbids_return_loading() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["outcome_returns_loaded"] is False
    assert definition["event"]["lookback_trading_days"] == 5


def test_weekly_signal_dates_use_last_available_trading_day() -> None:
    dates = ["20260105", "20260106", "20260109", "20260112", "20260115"]

    assert study.weekly_signal_dates(dates) == ["20260109", "20260115"]


def test_weekly_candidates_deduplicate_latest_limit_down_event() -> None:
    events = pd.DataFrame(
        [
            {
                "trade_date": "20260105",
                "ts_code": "000001.SZ",
                "name": "样本",
                "limit_type": "D",
            },
            {
                "trade_date": "20260108",
                "ts_code": "000001.SZ",
                "name": "样本",
                "limit_type": "D",
            },
            {
                "trade_date": "20260109",
                "ts_code": "000002.SZ",
                "name": "*ST样本",
                "limit_type": "D",
            },
        ]
    )
    calendar = ["20260105", "20260106", "20260107", "20260108", "20260109"]

    result = study.build_weekly_candidates(events, ["20260109"], calendar)

    assert result["ts_code"].tolist() == ["000001.SZ"]
    assert result["trade_date"].tolist() == ["20260108"]
