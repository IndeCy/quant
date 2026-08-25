"""异常成交额门面和恐慌反转研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.abnormal_amount import (
    load_abnormal_amount_snapshot,
    materialize_abnormal_amount,
)
from examples import capitulation_volume_feasibility_study as study
from examples import capitulation_volume_reversal_study as strategy_study
from factors.capitulation_reversal import score_capitulation_reversal_frame


def test_recent_and_baseline_windows_do_not_overlap() -> None:
    """近期20日与此前60日必须严格分离。"""
    connection = _build_market_connection()
    try:
        materialize_abnormal_amount(
            connection,
            lookback_start="20200101",
            research_start="20200101",
        )
        snapshot = load_abnormal_amount_snapshot(connection)
    finally:
        connection.close()

    row = snapshot.iloc[-2]
    assert row["recent_observations"] == 20
    assert row["baseline_observations"] == 60
    assert row["recent_amount_average"] == pytest.approx(200)
    assert row["baseline_amount_average"] == pytest.approx(100)
    assert row["abnormal_amount_ratio"] == pytest.approx(2.0)


def test_future_amount_does_not_change_prior_signal() -> None:
    """下一交易日巨量成交不得污染前一日信号。"""
    connection = _build_market_connection()
    try:
        materialize_abnormal_amount(
            connection,
            lookback_start="20200101",
            research_start="20200101",
        )
        snapshot = load_abnormal_amount_snapshot(connection)
    finally:
        connection.close()

    prior = snapshot.iloc[-2]
    future = snapshot.iloc[-1]
    assert prior["abnormal_amount_ratio"] == pytest.approx(2.0)
    assert future["abnormal_amount_ratio"] > prior["abnormal_amount_ratio"]


def test_factor_requires_both_loss_and_abnormal_volume() -> None:
    """未下跌或未放量的股票不得进入恐慌反转排序。"""
    frame = pd.DataFrame(
        {
            "symbol": ["PANIC", "MILD", "UP", "QUIET"],
            "return_20d": [-0.20, -0.05, 0.10, -0.20],
            "abnormal_amount_ratio": [2.0, 1.2, 2.0, 0.8],
        }
    )
    scored = score_capitulation_reversal_frame(frame).set_index("symbol")

    assert set(scored.index) == {"PANIC", "MILD"}
    assert scored.loc["PANIC", "factor_score"] > scored.loc["MILD", "factor_score"]


def test_feasibility_rejects_sparse_signal_months() -> None:
    """多数月份放量下跌样本不足时不得回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20211231", "20220131", "20220228"],
            "candidate_count": [1500, 1500, 1500],
            "signal_candidate_count": [100, 20, 100],
            "unique_volume_ratios": [100, 20, 100],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "ratio_p01": 1.01,
            "ratio_median": 1.2,
            "ratio_p99": 3.0,
            "return_p01": -0.3,
            "return_median": -0.1,
            "return_p99": -0.01,
        },
        {
            "duplicate_signal_symbol_rows": 0,
            "window_length_violations": 0,
            "median_spearman_return_vs_abnormal_amount": -0.1,
        },
        "20220228",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_feasibility_reuses_same_fingerprint_without_data_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同口径和数据版本必须复用，禁止再次扫描日线。"""
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
    """正式策略相同运行指纹不得再次启动回测。"""
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
            return {"reused": True, "strategy_id": strategy_study.STRATEGY_ID}

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
    """构造60日基线、20日近期和1日未来巨量数据。"""
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
    dates = pd.bdate_range("2020-01-01", periods=81)
    rows_adj: list[tuple[str, str, float]] = []
    rows_daily: list[tuple[str, str, float]] = []
    for index, value in enumerate(dates):
        trade_date = value.strftime("%Y%m%d")
        close = 100.0 if index < 60 else 100.0 - (index - 59)
        amount = 100.0 if index < 60 else 200.0
        if index == 80:
            amount = 2000.0
        rows_adj.append(("AAA.SZ", trade_date, close))
        rows_daily.append(("AAA.SZ", trade_date, amount))
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
        rows_adj,
    )
    connection.executemany(
        "INSERT INTO daily VALUES (?, ?, ?)",
        rows_daily,
    )
    return connection
