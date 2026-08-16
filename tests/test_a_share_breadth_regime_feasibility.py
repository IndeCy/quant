from __future__ import annotations

import pandas as pd

from examples import a_share_breadth_regime_feasibility_study as study


def test_definition_does_not_load_outcome_returns() -> None:
    assert study.RESEARCH_SPEC.definition["outcome_returns_loaded"] is False


def test_select_weekly_last_uses_last_available_date() -> None:
    daily = pd.DataFrame(
        {
            "trade_date": ["20260105", "20260109", "20260112", "20260115"],
            "universe_count": [10, 11, 12, 13],
            "breadth_ma60": [0.4, 0.5, 0.6, 0.7],
        }
    )

    weekly = study.select_weekly_last(daily)

    assert weekly["trade_date"].tolist() == ["20260109", "20260115"]
    assert weekly["breadth_ma60"].tolist() == [0.5, 0.7]
