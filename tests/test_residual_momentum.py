"""走步双因子残差动量数据与门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.residual_momentum import (
    build_style_factor_frame,
    materialize_residual_momentum,
)
from examples import residual_momentum_feasibility_study as study
from factors.residual_momentum import score_residual_momentum


def test_materialization_uses_separate_historical_windows() -> None:
    """Beta估计和残差评价必须分窗，且都早于信号日。"""
    dates = pd.bdate_range("2024-01-01", periods=10)
    market_returns = [0.0, 0.01, -0.01, 0.02, -0.02,
                      0.01, 0.015, -0.01, 0.50, -0.50]
    size_returns = [0.0, -0.005, 0.01, 0.005, -0.01,
                    0.02, -0.005, 0.01, 0.40, -0.40]
    stock_returns = [
        0.0,
        *[
            0.001 + 1.2 * market_returns[index]
            + 0.8 * size_returns[index]
            for index in range(1, 10)
        ],
    ]
    close = [10.0]
    for value in stock_returns[1:]:
        close.append(close[-1] * (1.0 + value))
    style = pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "trade_index": range(10),
            "market_return": market_returns,
            "size_return": size_returns,
        }
    )
    source = pd.DataFrame(
        {
            "ts_code": ["A"] * 10,
            "trade_date": dates.strftime("%Y%m%d"),
            "close_qfq": close,
        }
    )
    connection = duckdb.connect()
    connection.register("source", source)
    connection.execute(
        "CREATE TABLE daily_adj_cache AS SELECT * FROM source"
    )

    materialize_residual_momentum(
        connection,
        style,
        [dates[-1].strftime("%Y%m%d")],
        estimation_start_lag=8,
        estimation_end_lag=5,
        evaluation_start_lag=4,
        evaluation_end_lag=2,
        minimum_estimation_observations=4,
        minimum_evaluation_observations=3,
        source_start=dates[0].strftime("%Y%m%d"),
    )
    row = connection.execute(
        """
        SELECT market_beta, size_beta, residual_momentum,
               signal_index-evaluation_max_index AS skip_gap
        FROM residual_momentum_features
        """
    ).fetchone()

    assert row[0] == pytest.approx(1.2)
    assert row[1] == pytest.approx(0.8)
    assert row[2] == pytest.approx(0.003)
    assert row[3] == 2


def test_style_factor_uses_relative_csi500_return() -> None:
    """规模因子必须是中证500收益减沪深300收益。"""
    index = pd.bdate_range("2024-01-01", periods=3)
    frame = build_style_factor_frame(
        pd.Series([1.0, 1.1, 1.1], index=index),
        pd.Series([1.0, 1.2, 1.32], index=index),
    )

    assert frame.loc[1, "market_return"] == pytest.approx(0.10)
    assert frame.loc[1, "size_return"] == pytest.approx(0.10)
    assert frame.loc[2, "size_return"] == pytest.approx(0.10)


def test_higher_residual_momentum_receives_higher_score() -> None:
    """累计特质收益更高的股票必须获得更高横截面分数。"""
    scored = score_residual_momentum(
        pd.DataFrame(
            {
                "symbol": ["A", "B", "C"],
                "residual_momentum": [-0.1, 0.3, 0.1],
            }
        )
    ).set_index("symbol")

    assert scored.loc["B", "factor_score"] > scored.loc["C", "factor_score"]
    assert scored.loc["C", "factor_score"] > scored.loc["A", "factor_score"]


def test_feasibility_counts_invalid_factor_values() -> None:
    """门禁必须准确记录不可用的残差动量值。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"],
            "symbol": ["A"],
            "residual_momentum": [float("nan")],
            "evaluation_stock_sum": [0.1],
            "market_beta": [1.0],
            "evaluation_market_sum": [0.1],
            "size_beta": [0.0],
            "evaluation_size_sum": [0.0],
            "signal_index": [300],
            "evaluation_max_index": [280],
            "estimation_max_index": [179],
            "determinant": [1.0],
            "estimation_observations": [120],
            "evaluation_observations": [90],
        }
    )
    monthly = pd.DataFrame(
        {
            "candidate_count": [1],
            "unique_factor_values": [0],
            "top40_count": [1],
            "top40_median_adv_rmb": [0.0],
            "top40_tradable_share": [0.0],
            "spearman_intermediate_momentum": [0.0],
            "spearman_vol60": [0.0],
            "spearman_ret120": [0.0],
        }
    )

    result = study.evaluate_feasibility(
        candidates,
        monthly,
        "20240131",
    )

    assert result["invalid_rows"] == 1
    assert result["checks"]["zero_invalid_rows"] is False


def test_same_fingerprint_reuses_without_market_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """相同数据指纹复用时不得扫描行情或计算因子。"""
    for relative in [
        "daily_adj_19901219_20260615.duckdb",
        "data/live_market_increment.duckdb",
        "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
        "data/benchmark_increment.duckdb",
    ]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")

    class ReusedAttempt:
        should_run = False

        @staticmethod
        def cached_result() -> dict[str, object]:
            return {"reused": True}

    monkeypatch.setattr(
        study,
        "begin_research_attempt",
        lambda *args, **kwargs: ReusedAttempt(),
    )
    monkeypatch.setattr(
        study,
        "_calculate",
        lambda *args, **kwargs: pytest.fail("不应扫描行情"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True
