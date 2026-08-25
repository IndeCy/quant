"""低下行 Beta 数据门面、因子和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.downside_beta import (
    create_downside_beta_signal_dates,
    load_downside_beta_snapshot,
    materialize_downside_beta,
)
from examples import downside_beta_feasibility_study as study
from examples import downside_beta_study as strategy_study
from factors.downside_beta import score_downside_beta_frame


def test_downside_beta_uses_only_trailing_negative_market_days() -> None:
    """下行 Beta 应只使用窗口内基准负收益日。"""
    dates = pd.date_range("2023-01-01", periods=7, freq="D")
    market_returns = pd.Series(
        [0.01, -0.02, 0.03, -0.01, 0.02, -0.03],
        index=dates[1:],
    )
    benchmark = pd.Series(index=dates, dtype=float)
    benchmark.iloc[0] = 1.0
    for index, value in enumerate(market_returns, start=1):
        benchmark.iloc[index] = benchmark.iloc[index - 1] * (1.0 + value)

    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE features(trade_date VARCHAR, symbol VARCHAR, ret DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO features VALUES (?, ?, ?)",
        [
            (
                date.strftime("%Y%m%d"),
                "000001.SZ",
                float(value * 2.0),
            )
            for date, value in market_returns.items()
        ],
    )
    signal_date = dates[-1].strftime("%Y%m%d")
    try:
        create_downside_beta_signal_dates(connection, [signal_date])
        materialize_downside_beta(
            connection,
            benchmark,
            window=6,
            min_observations=5,
            min_down_observations=2,
        )
        snapshot = load_downside_beta_snapshot(connection)
    finally:
        connection.close()

    assert len(snapshot) == 1
    row = snapshot.iloc[0]
    assert row["observations"] == 6
    assert row["downside_observations"] == 3
    assert row["downside_beta"] == pytest.approx(2.0)
    assert row["upside_beta"] == pytest.approx(2.0)
    assert row["total_beta"] == pytest.approx(2.0)


def test_downside_beta_does_not_change_when_future_returns_are_appended() -> None:
    """追加信号日后的行情不能改变既有下行 Beta。"""
    dates = pd.date_range("2023-01-01", periods=8, freq="D")
    returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, -0.50]
    benchmark = pd.Series(index=dates, dtype=float)
    benchmark.iloc[0] = 1.0
    for index, value in enumerate(returns, start=1):
        benchmark.iloc[index] = benchmark.iloc[index - 1] * (1.0 + value)
    signal_date = dates[-2].strftime("%Y%m%d")

    def calculate(include_future: bool) -> float:
        connection = duckdb.connect()
        connection.execute(
            "CREATE TABLE features(trade_date VARCHAR, symbol VARCHAR, ret DOUBLE)"
        )
        end = len(returns) if include_future else len(returns) - 1
        connection.executemany(
            "INSERT INTO features VALUES (?, ?, ?)",
            [
                (
                    dates[index].strftime("%Y%m%d"),
                    "000001.SZ",
                    returns[index - 1] * 1.5,
                )
                for index in range(1, end + 1)
            ],
        )
        try:
            create_downside_beta_signal_dates(connection, [signal_date])
            materialize_downside_beta(
                connection,
                benchmark,
                window=6,
                min_observations=5,
                min_down_observations=2,
            )
            return float(
                load_downside_beta_snapshot(connection).iloc[0]["downside_beta"]
            )
        finally:
            connection.close()

    assert calculate(False) == pytest.approx(calculate(True))


def test_factor_prefers_lower_downside_beta() -> None:
    """样本完整且总Beta正常时，下行Beta更低者得分更高。"""
    frame = pd.DataFrame(
        {
            "symbol": ["DEFENSIVE", "CYCLICAL"],
            "downside_beta": [0.4, 1.3],
            "total_beta": [0.7, 1.1],
            "observations": [252, 252],
            "downside_observations": [110, 110],
        }
    )

    scored = score_downside_beta_frame(frame).set_index("symbol")

    assert scored.loc["DEFENSIVE", "factor_score"] > scored.loc[
        "CYCLICAL", "factor_score"
    ]


def test_factor_filters_negative_or_under_observed_beta() -> None:
    """噪声型负Beta和样本不足记录不得进入长仓排序。"""
    frame = pd.DataFrame(
        {
            "symbol": ["VALID", "NEGATIVE", "SHORT"],
            "downside_beta": [0.7, -0.2, 0.3],
            "total_beta": [0.8, 0.2, 0.5],
            "observations": [252, 252, 199],
            "downside_observations": [100, 100, 59],
        }
    )

    result = score_downside_beta_frame(frame)

    assert result["symbol"].tolist() == ["VALID"]


def test_feasibility_rejects_semantic_duplicate_of_low_beta() -> None:
    """与低总Beta近乎同序时，应在收益回测前终止。"""
    monthly = pd.DataFrame(
        {
            "signal_date": ["20231229", "20240131", "20240229"],
            "candidate_count": [1200, 1200, 1200],
            "unique_factor_values": [1100, 1100, 1100],
            "top40_median_adv_rmb": [20_000_000.0] * 3,
            "top40_tradable_share": [1.0] * 3,
        }
    )
    result = study.evaluate_feasibility(
        monthly,
        {
            "downside_p01": 0.1,
            "downside_median": 0.8,
            "downside_p99": 1.8,
            "total_beta_median": 0.9,
            "upside_beta_median": 1.0,
        },
        {
            "duplicate_signal_symbol_rows": 0,
            "observation_violations": 0,
            "median_spearman_with_low_total_beta": 0.95,
            "median_spearman_with_low_vol60": 0.50,
            "median_spearman_with_amount20": 0.0,
            "median_spearman_with_ret120": 0.0,
            "median_top40_overlap_with_low_total_beta": 0.8,
            "median_top40_overlap_with_low_vol60": 0.3,
        },
        "20240229",
    )

    assert result["passed"] is False
    assert result["checks"]["distinct_from_low_total_beta"] is False


def test_feasibility_reuses_fingerprint_without_data_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义和数据版本必须直接复用历史研究。"""
    filenames = [
        "daily_adj_19901219_20260615.duckdb",
        "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
    ]
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"fixture")
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "live_market_increment.duckdb").write_bytes(b"fixture")
    (data_dir / "benchmark_increment.duckdb").write_bytes(b"fixture")

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
        lambda *args, **kwargs: pytest.fail("不应读取研究数据"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True


def test_formal_target_builder_selects_lowest_downside_beta() -> None:
    """正式组合应选择下行 Beta 最低的40只并等权。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"] * 50,
            "symbol": [f"{index:06d}.SZ" for index in range(50)],
            "downside_beta": [index / 100.0 for index in range(50)],
            "total_beta": [0.8] * 50,
            "upside_beta": [0.7] * 50,
            "observations": [252] * 50,
            "downside_observations": [100] * 50,
        }
    )

    targets, holdings, counts = strategy_study.build_targets(candidates)

    selected = set(targets["20240131"])
    assert len(selected) == 40
    assert "000000.SZ" in selected
    assert "000039.SZ" in selected
    assert "000049.SZ" not in selected
    assert all(weight == pytest.approx(0.025) for weight in targets["20240131"].values())
    assert len(holdings) == 40
    assert counts["latest"] == 50


def test_formal_gate_rejects_quality_redundancy() -> None:
    """收益合格但与 Quality 高度同源时仍不得晋级。"""
    good = {
        "annualized_return": 0.10,
        "max_drawdown": -0.20,
        "sharpe": 0.70,
        "calmar": 0.50,
        "excess_return": 0.10,
        "annual_turnover": 6.0,
    }
    metrics = {
        "2015_2017": good,
        "2018_2020": good,
        "2021_2023": good,
        "2024_latest": good,
        "full": good,
    }

    result = strategy_study.evaluate_gate(metrics, quality_correlation=0.90)

    assert result["passed"] is False
    assert result["checks"]["quality_correlation_at_most_075"] is False


def test_formal_study_reuses_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同正式研究指纹必须复用，不得再次启动回测。"""
    filenames = [
        "daily_adj_19901219_20260615.duckdb",
        "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
    ]
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"fixture")
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "live_market_increment.duckdb").write_bytes(b"fixture")
    (data_dir / "benchmark_increment.duckdb").write_bytes(b"fixture")

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
