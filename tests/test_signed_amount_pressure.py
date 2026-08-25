"""成交额加权涨跌压力门面和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.signed_amount_pressure import (
    load_signed_amount_pressure_snapshot,
    materialize_signed_amount_pressure,
)
from examples import signed_amount_pressure_feasibility_study as study
from examples import signed_amount_pressure_study as strategy_study
from factors.signed_amount_pressure import score_signed_amount_pressure_frame


def test_pressure_weights_amount_by_daily_return_direction() -> None:
    """上涨日成交额记正、下跌日记负、平盘记零。"""
    connection = _build_market_connection()
    try:
        materialize_signed_amount_pressure(
            connection,
            window=4,
            lookback_start="20200101",
            research_start="20200101",
        )
        snapshot = load_signed_amount_pressure_snapshot(connection)
    finally:
        connection.close()

    row = snapshot.iloc[-2]
    expected = (200 - 100 + 300) / (200 + 100 + 100 + 300)
    assert row["signed_amount_pressure"] == pytest.approx(expected)
    assert row["positive_amount_share"] == pytest.approx(500 / 700)
    assert row["negative_amount_share"] == pytest.approx(100 / 700)
    assert row["neutral_amount_share"] == pytest.approx(100 / 700)


def test_future_signed_amount_does_not_change_prior_signal() -> None:
    """下一交易日的巨额下跌成交不得污染前一日压力。"""
    connection = _build_market_connection()
    try:
        materialize_signed_amount_pressure(
            connection,
            window=4,
            lookback_start="20200101",
            research_start="20200101",
        )
        snapshot = load_signed_amount_pressure_snapshot(connection)
    finally:
        connection.close()

    prior = snapshot.iloc[-2]
    future = snapshot.iloc[-1]
    assert prior["signed_amount_pressure"] > 0
    assert future["signed_amount_pressure"] < prior["signed_amount_pressure"]


def test_factor_prefers_stronger_positive_pressure() -> None:
    """正向成交额压力更高的股票必须获得更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["BUYING", "NEUTRAL", "SELLING", "INVALID"],
            "signed_amount_pressure": [0.6, 0.0, -0.5, 1.1],
        }
    )
    scored = score_signed_amount_pressure_frame(frame).set_index("symbol")

    assert set(scored.index) == {"BUYING", "NEUTRAL", "SELLING"}
    assert scored.loc["BUYING", "factor_score"] > scored.loc["SELLING", "factor_score"]


def test_feasibility_rejects_concentrated_or_sparse_months() -> None:
    """单日成交主导或候选不足时不得进入正式回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131", "20220228"],
            "candidate_count": [1500, 500, 1500],
            "unique_factor_values": [1400, 500, 1400],
            "maximum_daily_concentration_median": [0.1, 0.5, 0.1],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "pressure_p01": -0.5,
            "pressure_median": 0.0,
            "pressure_p99": 0.5,
            "return_p01": -0.2,
            "return_median": 0.0,
            "return_p99": 0.2,
        },
        {
            "duplicate_signal_symbol_rows": 0,
            "window_length_violations": 0,
            "range_violations": 0,
            "median_spearman_with_return_20d": 0.5,
        },
        "20220228",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_feasibility_reuses_same_fingerprint_without_data_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同运行指纹必须复用，禁止再次扫描日线。"""
    files = [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {"reused": True, "experiment_id": study.EXPERIMENT_ID}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应扫描日线"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_strategy_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正式策略相同指纹必须复用，禁止再次启动回测。"""
    files = [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    class ReusedAttempt:
        should_run = False

        def cached_result(self) -> dict[str, object]:
            return {
                "reused": True,
                "strategy_id": strategy_study.STRATEGY_ID,
            }

    monkeypatch.setattr(
        strategy_study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        strategy_study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应重新回测"),
    )

    result = strategy_study.run_study(
        strategy_study.RuntimePaths(tmp_path),
        "20260726",
    )

    assert result["reused"] is True


def _build_market_connection() -> duckdb.DuckDBPyConnection:
    """构造涨、跌、平和未来巨量下跌日。"""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE daily_adj_cache(
            ts_code VARCHAR,
            trade_date VARCHAR,
            close_qfq DOUBLE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE daily(
            ts_code VARCHAR,
            trade_date VARCHAR,
            amount DOUBLE
        )
        """
    )
    dates = pd.bdate_range("2020-01-01", periods=6)
    closes = [10.0, 11.0, 10.0, 10.0, 12.0, 8.0]
    amounts = [50.0, 200.0, 100.0, 100.0, 300.0, 2000.0]
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
        [
            ("AAA.SZ", date.strftime("%Y%m%d"), close)
            for date, close in zip(dates, closes, strict=True)
        ],
    )
    connection.executemany(
        "INSERT INTO daily VALUES (?, ?, ?)",
        [
            ("AAA.SZ", date.strftime("%Y%m%d"), amount)
            for date, amount in zip(dates, amounts, strict=True)
        ],
    )
    return connection
