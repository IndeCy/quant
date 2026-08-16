"""Amihud 非流动性门面、因子和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.amihud_illiquidity import (
    load_amihud_illiquidity_snapshot,
    materialize_amihud_illiquidity,
)
from examples import amihud_illiquidity_feasibility_study as study
from examples import amihud_illiquidity_study as strategy_study
from factors.amihud_illiquidity import score_amihud_illiquidity_frame


def test_amihud_uses_absolute_qfq_return_per_rmb_amount() -> None:
    """上涨和下跌都按绝对收益除以人民币成交额计入冲击。"""
    connection = _build_market_connection()
    try:
        materialize_amihud_illiquidity(
            connection,
            window=3,
            lookback_start="20200101",
            research_start="20200101",
        )
        snapshot = load_amihud_illiquidity_snapshot(connection)
    finally:
        connection.close()

    row = snapshot.iloc[-2]
    impacts = [
        abs(11 / 10 - 1) / 100_000,
        abs(10 / 11 - 1) / 200_000,
        abs(12 / 10 - 1) / 100_000,
    ]
    assert row["amihud_illiquidity"] == pytest.approx(sum(impacts) / 3)
    assert row["average_amount_rmb"] == pytest.approx(400_000 / 3)


def test_future_low_amount_crash_does_not_change_prior_amihud() -> None:
    """未来低成交额暴跌不得污染此前非流动性信号。"""
    connection = _build_market_connection()
    try:
        materialize_amihud_illiquidity(
            connection,
            window=3,
            lookback_start="20200101",
            research_start="20200101",
        )
        snapshot = load_amihud_illiquidity_snapshot(connection)
    finally:
        connection.close()

    assert snapshot.iloc[-1]["amihud_illiquidity"] > snapshot.iloc[-2][
        "amihud_illiquidity"
    ]


def test_factor_prefers_higher_illiquidity() -> None:
    """单位成交额冲击更高的股票应获得更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["ILLIQUID", "LIQUID", "SHORT"],
            "amihud_illiquidity": [3e-9, 1e-10, 5e-9],
            "observations": [60, 60, 59],
        }
    )

    scored = score_amihud_illiquidity_frame(frame).set_index("symbol")

    assert set(scored.index) == {"ILLIQUID", "LIQUID"}
    assert scored.loc["ILLIQUID", "factor_score"] > scored.loc[
        "LIQUID", "factor_score"
    ]


def test_feasibility_rejects_untradable_top40() -> None:
    """高冲击股票日均成交额不足时不得进入回测。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20231229", "20240131", "20240229"],
            "candidate_count": [1500, 1500, 1500],
            "unique_factor_values": [1400, 1400, 1400],
            "impact_concentration_median": [0.2, 0.2, 0.2],
            "top40_median_adv_rmb": [20e6, 2e6, 20e6],
            "top40_tradable_share": [1.0, 0.5, 1.0],
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "illiquidity_p01": 1e-12,
            "illiquidity_median": 1e-10,
            "illiquidity_p99": 1e-8,
            "amount20_p01_rmb": 1e6,
            "amount20_median_rmb": 20e6,
            "amount20_p99_rmb": 1e9,
        },
        {
            "duplicate_signal_symbol_rows": 0,
            "window_length_violations": 0,
            "range_violations": 0,
            "median_spearman_with_amount20": -0.8,
            "median_spearman_with_vol60": 0.2,
            "median_spearman_with_ret120": 0.0,
        },
        "20240229",
    )

    assert result["passed"] is False
    assert result["checks"]["locked_qualified_month_share"] is False


def test_diagnostics_reads_normalized_rmb_amount_field() -> None:
    """相关性诊断必须读取标准化后的人民币成交额字段。"""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE amihud_illiquidity_features(
            trade_date VARCHAR,
            symbol VARCHAR,
            observations INTEGER,
            amihud_illiquidity DOUBLE,
            maximum_daily_impact_share DOUBLE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO amihud_illiquidity_features
        VALUES ('20200131', 'A', 60, 2e-9, 0.2),
               ('20200131', 'B', 60, 1e-9, 0.3)
        """
    )
    panel = pd.DataFrame(
        {
            "signal_date": ["20200131", "20200131"],
            "amihud_illiquidity": [2e-9, 1e-9],
            "amount20_rmb": [10e6, 20e6],
            "vol60": [0.03, 0.02],
            "ret120": [0.1, 0.2],
        }
    )

    result = study.load_diagnostics(connection, panel)
    connection.close()

    assert result["median_spearman_with_amount20"] == pytest.approx(-1.0)


def test_feasibility_reuses_fingerprint_without_data_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同数据与定义指纹必须复用，不得重新扫描日线。"""
    base = tmp_path / "daily_adj_19901219_20260615.duckdb"
    base.write_bytes(b"fixture")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"fixture")

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
        lambda *args, **kwargs: pytest.fail("不应重新扫描日线"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_formal_gate_requires_cross_fold_stability() -> None:
    """全样本合格也不能掩盖两段负收益。"""
    good = _good_metrics()
    losing = {**good, "annualized_return": -0.01, "sharpe": -0.1}
    metrics = {
        "2015_2017": losing,
        "2018_2020": losing,
        "2021_2023": good,
        "2024_latest": good,
        "full": good,
    }

    result = strategy_study.evaluate_gate(metrics, quality_correlation=0.5)

    assert result["passed"] is False
    assert result["positive_folds"] == 2


def test_strategy_reuses_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """正式研究相同指纹必须复用，不得再次执行回测。"""
    base = tmp_path / "daily_adj_19901219_20260615.duckdb"
    base.write_bytes(b"fixture")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"fixture")

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


def _good_metrics() -> dict[str, float]:
    """构造一组通过收益、风险与成本门槛的指标。"""
    return {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": 6.0,
        "trade_count": 20.0,
        "execution_cost_impact": 0.01,
    }


def _build_market_connection() -> duckdb.DuckDBPyConnection:
    """构造上涨、下跌及未来低成交额暴跌样本。"""
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
    dates = pd.bdate_range("2020-01-01", periods=5)
    closes = [10.0, 11.0, 10.0, 12.0, 6.0]
    amounts = [100.0, 100.0, 200.0, 100.0, 1.0]
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
