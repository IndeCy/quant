import pandas as pd

from examples.quality_factor_purity_study import build_neutralized_selection, score_within_group


def test_score_within_group_ranks_factors_inside_group():
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "group": ["X", "X", "Y", "Y"],
            "roe": [1.0, 2.0, 100.0, 200.0],
            "roa": [1.0, 2.0, 100.0, 200.0],
            "ocf_to_or": [1.0, 2.0, 100.0, 200.0],
        }
    )

    scored = score_within_group(frame, "group")

    assert scored.loc[scored["symbol"].eq("B"), "neutral_score"].iloc[0] == 1.0
    assert scored.loc[scored["symbol"].eq("D"), "neutral_score"].iloc[0] == 1.0


def test_build_neutralized_selection_returns_top_symbols_by_signal_date():
    frame = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 3,
            "symbol": ["A", "B", "C"],
            "group": ["X", "X", "X"],
            "roe": [1.0, 3.0, 2.0],
            "roa": [1.0, 3.0, 2.0],
            "ocf_to_or": [1.0, 3.0, 2.0],
        }
    )

    selections, holdings = build_neutralized_selection(frame, "group", top_n=2)

    assert selections["20240131"] == ["B", "C"]
    assert holdings["rank"].tolist() == [1, 2]
