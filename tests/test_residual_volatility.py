"""滚动特质波动率特征、评分和研究去重测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.residual_volatility import (
    load_residual_volatility_snapshot,
    materialize_residual_volatility,
)
from examples import residual_volatility_study as study
from factors.residual_volatility import score_low_residual_volatility_frame


def test_market_following_stock_has_lower_residual_volatility() -> None:
    """完全跟随基准的股票应比带独立噪声的股票残差波动更低。"""
    dates = pd.date_range("2020-01-01", periods=7, freq="D")
    benchmark_returns = [0.0, 0.01, -0.01, 0.02, -0.02, 0.01, -0.01]
    benchmark_values = [100.0]
    for value in benchmark_returns[1:]:
        benchmark_values.append(benchmark_values[-1] * (1 + value))
    benchmark = pd.Series(benchmark_values, index=dates)
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, "
        "close_qfq DOUBLE)"
    )
    rows = []
    exact = 50.0
    noisy = 50.0
    noises = [0.0, 0.02, -0.01, 0.03, -0.02, 0.01, -0.03]
    for index, date in enumerate(dates):
        if index:
            exact *= 1 + 2 * benchmark_returns[index]
            noisy *= 1 + benchmark_returns[index] + noises[index]
        rows.extend(
            [
                ("EXACT", date.strftime("%Y%m%d"), exact),
                ("NOISY", date.strftime("%Y%m%d"), noisy),
            ]
        )
    connection.executemany("INSERT INTO daily_adj_cache VALUES (?, ?, ?)", rows)
    materialize_residual_volatility(
        connection,
        benchmark,
        window=5,
        lookback_start="20200101",
        research_start="20200101",
    )
    result = load_residual_volatility_snapshot(connection)
    connection.close()
    latest = result[result["trade_date"].eq("20200107")].set_index("symbol")

    assert latest.loc["EXACT", "beta"] == pytest.approx(2.0, abs=0.03)
    assert latest.loc["EXACT", "residual_volatility"] < 0.01
    assert (
        latest.loc["NOISY", "residual_volatility"]
        > latest.loc["EXACT", "residual_volatility"]
    )


def test_factor_prefers_lower_residual_volatility() -> None:
    """更低的特质波动必须得到更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["LOW", "HIGH", "INVALID"],
            "residual_volatility": [0.10, 0.40, -1.0],
        }
    )
    scored = score_low_residual_volatility_frame(frame).set_index("symbol")

    assert set(scored.index) == {"LOW", "HIGH"}
    assert scored.loc["LOW", "factor_score"] > scored.loc["HIGH", "factor_score"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义和行情版本不能重复运行回测。"""
    files = [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
        tmp_path / "etf_lof_reits_daily_adj_20041220_20260617.duckdb",
        tmp_path / "data" / "benchmark_increment.duckdb",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

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

    result = study.run_study(study.RuntimePaths(tmp_path), "20260725")

    assert result["reused"] is True
