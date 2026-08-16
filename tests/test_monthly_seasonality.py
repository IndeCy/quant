"""跨年月份季节性研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.seasonality_features import (
    load_monthly_seasonality_snapshot,
    materialize_monthly_seasonality,
)
from examples import monthly_seasonality_study as study
from factors.monthly_seasonality import score_monthly_seasonality_frame


def test_seasonality_uses_prior_same_month_and_blocks_future_month() -> None:
    """信号只能读取历史同月收益，信号后的极端收益不可进入均值。"""
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TEMP TABLE daily_adj_cache(
                ts_code VARCHAR,
                trade_date VARCHAR,
                close_qfq DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
            [
                ("000001.SZ", "20171229", 100),
                ("000001.SZ", "20180131", 110),
                ("000001.SZ", "20181228", 100),
                ("000001.SZ", "20190131", 105),
                ("000001.SZ", "20191231", 100),
                ("000001.SZ", "20200123", 120),
                ("000001.SZ", "20201231", 100),
                ("000001.SZ", "20210129", 300),
            ],
        )
        connection.execute("CREATE TEMP TABLE features(trade_date VARCHAR)")
        connection.executemany(
            "INSERT INTO features VALUES (?)",
            [("20201231",), ("20210129",)],
        )
        materialize_monthly_seasonality(connection)
        snapshot = load_monthly_seasonality_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["signal_date"].tolist() == ["20201231"]
    row = snapshot.iloc[0]
    assert row["target_month"] == 1
    assert row["observations"] == 3
    assert row["seasonal_mean_return"] == pytest.approx((0.10 + 0.05 + 0.20) / 3)
    assert row["seasonal_win_rate"] == pytest.approx(1.0)


def test_seasonality_factor_prefers_higher_historical_same_month_return() -> None:
    """同月历史收益更高的股票应获得更高分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW", "MID"],
            "seasonal_mean_return": [0.20, -0.05, 0.08],
            "observations": [5, 5, 3],
        }
    )

    result = score_monthly_seasonality_frame(frame).set_index("symbol")

    assert result.loc["HIGH", "factor_score"] > result.loc["MID", "factor_score"]
    assert result.loc["MID", "factor_score"] > result.loc["LOW", "factor_score"]


def test_seasonality_factor_requires_three_observations() -> None:
    """历史同月样本不足三次时不能形成评分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["ENOUGH", "SHORT"],
            "seasonal_mean_return": [0.10, 0.30],
            "observations": [3, 2],
        }
    )

    result = score_monthly_seasonality_frame(frame)

    assert result["symbol"].tolist() == ["ENOUGH"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同行情版本和研究定义不得重复回测。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "strategy_id": study.STRATEGY_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新计算"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True
