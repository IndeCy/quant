import pandas as pd
import pytest

from examples.quality_attribution_audit import annual_strategy_vs_benchmark, bucket_market_cap, summarize_exposure


def test_bucket_market_cap_labels_relative_size():
    series = pd.Series([10.0, 20.0, 30.0, 40.0])

    buckets = bucket_market_cap(series)

    assert buckets.tolist() == ["小盘", "中小盘", "中大盘", "大盘"]


def test_summarize_exposure_outputs_mean_and_median():
    frame = pd.DataFrame({"pb": [1.0, 2.0, 100.0], "pe": [10.0, 20.0, 30.0]})

    summary = summarize_exposure(frame, ["pb", "pe"])

    assert summary.loc[summary["指标"].eq("pb"), "均值"].iloc[0] == 34.333333333333336
    assert summary.loc[summary["指标"].eq("pe"), "中位数"].iloc[0] == 20.0


def test_annual_returns_use_previous_year_last_close():
    strategy = pd.Series(
        [100.0, 110.0, 120.0],
        index=pd.to_datetime(["2025-12-31", "2026-01-05", "2026-06-15"]),
    )
    benchmark = pd.Series(
        [1.0, 1.05, 1.2],
        index=pd.to_datetime(["2025-12-31", "2026-01-05", "2026-06-15"]),
    )

    annual = annual_strategy_vs_benchmark(strategy, benchmark)

    row = annual.loc[annual["年份"].eq(2026)].iloc[0]
    assert row["Quality收益"] == pytest.approx(0.2)
    assert row["沪深300收益"] == pytest.approx(0.2)
