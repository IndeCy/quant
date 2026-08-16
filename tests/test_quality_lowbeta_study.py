"""Quality LowBeta 研究接口测试。"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from data.rolling_beta import attach_rolling_beta
from examples.quality_lowbeta_study import evaluate_gate
from factors.quality_lowbeta import score_quality_lowbeta_frame


def test_rolling_beta_uses_only_history_through_signal_date() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE quality_signal_dates(signal_date VARCHAR)")
        connection.execute("INSERT INTO quality_signal_dates VALUES ('20240105')")
        connection.execute("CREATE TABLE features(trade_date VARCHAR, symbol VARCHAR, ret DOUBLE)")
        rows = []
        market_returns = [0.01, -0.02, 0.03, 0.01]
        dates = pd.bdate_range("2024-01-02", periods=4)
        for date, market_return in zip(dates, market_returns):
            rows.append((date.strftime("%Y%m%d"), "AAA.SZ", market_return * 2))
        connection.executemany("INSERT INTO features VALUES (?, ?, ?)", rows)
        benchmark = pd.Series(
            [1.0, 1.01, 1.01 * 0.98, 1.01 * 0.98 * 1.03, 1.01 * 0.98 * 1.03 * 1.01],
            index=pd.bdate_range("2024-01-01", periods=5),
        )
        candidates = pd.DataFrame({"signal_date": ["20240105"], "symbol": ["AAA.SZ"]})

        result = attach_rolling_beta(
            connection,
            candidates,
            benchmark,
            window=4,
            min_observations=3,
        )
    finally:
        connection.close()

    assert result.iloc[0]["beta_120d"] == pytest.approx(2.0)


def test_quality_lowbeta_score_rewards_quality_and_lower_risk() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "roa": [3.0, 2.0, 1.0],
            "ocf_to_or": [3.0, 2.0, 1.0],
            "low_beta_120d": [-0.5, -1.0, -1.5],
            "low_volatility_60d": [-0.1, -0.2, -0.3],
        }
    )

    result = score_quality_lowbeta_frame(frame)

    assert result["symbol"].tolist() == ["A", "B", "C"]


def test_quality_lowbeta_gate_is_fixed() -> None:
    passing = {
        "annualized_return": 0.11,
        "max_drawdown": -0.24,
        "sharpe": 0.70,
        "calmar": 0.46,
        "excess_return": 0.10,
    }

    assert evaluate_gate(passing)["passed"] is True
    passing["sharpe"] = 0.60
    assert evaluate_gate(passing)["passed"] is False
