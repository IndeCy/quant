import pandas as pd

from examples.quality_strategy_v1 import score_quality_frame, winsorize_series, zscore_series


def test_winsorize_series_caps_extreme_values():
    series = pd.Series([1.0, 2.0, 3.0, 100.0])

    capped = winsorize_series(series, lower=0.25, upper=0.75)

    assert capped.tolist() == [1.75, 2.0, 3.0, 27.25]


def test_zscore_series_uses_population_standard_deviation():
    series = pd.Series([1.0, 2.0, 3.0])

    zscore = zscore_series(series)

    assert round(float(zscore.mean()), 10) == 0.0
    assert round(float(zscore.std(ddof=0)), 10) == 1.0


def test_score_quality_frame_equal_weights_three_factors():
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "roe": [30.0, 20.0, 10.0],
            "roa": [20.0, 10.0, 0.0],
            "ocf_to_or": [15.0, 10.0, 5.0],
        }
    )

    scored = score_quality_frame(frame)

    assert scored.iloc[0]["symbol"] == "A"
    assert scored.iloc[-1]["symbol"] == "C"
    assert "quality_score" in scored.columns


def test_score_quality_frame_drops_missing_factor_rows():
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "roe": [30.0, None],
            "roa": [20.0, 10.0],
            "ocf_to_or": [15.0, 5.0],
        }
    )

    scored = score_quality_frame(frame)

    assert scored["symbol"].tolist() == ["A"]
