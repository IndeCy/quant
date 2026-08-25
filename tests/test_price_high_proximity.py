"""52周高点接近度特征、因子和研究去重测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.price_high import (
    load_price_breakout_snapshot,
    load_price_high_snapshot,
    materialize_price_high_breakout,
    materialize_price_high_proximity,
)
from examples import price_high_proximity_study as study
from factors.price_high_proximity import score_price_high_proximity_frame
from factors.price_high_proximity import score_price_high_breakout_frame


def test_price_high_uses_current_and_prior_rows_only() -> None:
    """滚动最高价不得读取信号日之后的更高价格。"""
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, "
        "close_qfq DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
        [
            ("A", "20200101", 10.0),
            ("A", "20200102", 12.0),
            ("A", "20200103", 9.0),
            ("A", "20200104", 20.0),
        ],
    )
    materialize_price_high_proximity(
        connection,
        window=3,
        lookback_start="20200101",
        research_start="20200101",
    )
    result = load_price_high_snapshot(connection).set_index("trade_date")
    connection.close()

    assert result.loc["20200103", "max_close"] == pytest.approx(12.0)
    assert result.loc["20200103", "high_proximity"] == pytest.approx(0.75)
    assert result.loc["20200104", "max_close"] == pytest.approx(20.0)


def test_factor_prefers_price_closer_to_52_week_high() -> None:
    """高点接近度更高的股票必须得到更高横截面分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["NEAR", "MID", "INVALID"],
            "high_proximity": [0.99, 0.80, 1.20],
        }
    )
    scored = score_price_high_proximity_frame(frame).set_index("symbol")

    assert set(scored.index) == {"NEAR", "MID"}
    assert scored.loc["NEAR", "factor_score"] > scored.loc["MID", "factor_score"]


def test_breakout_uses_prior_window_and_breaks_new_high_ties() -> None:
    """前高窗口必须排除当日，并保留不同突破幅度。"""
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, "
        "close_qfq DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
        [
            ("A", "20200101", 10.0),
            ("A", "20200102", 12.0),
            ("A", "20200103", 15.0),
            ("B", "20200101", 10.0),
            ("B", "20200102", 12.0),
            ("B", "20200103", 13.0),
        ],
    )
    materialize_price_high_breakout(
        connection,
        window=2,
        lookback_start="20200101",
        research_start="20200101",
    )
    result = load_price_breakout_snapshot(connection)
    connection.close()
    latest = result[result["trade_date"].eq("20200103")]
    scored = score_price_high_breakout_frame(latest).set_index("symbol")

    assert scored.loc["A", "breakout_strength"] == pytest.approx(1.25)
    assert scored.loc["B", "breakout_strength"] == pytest.approx(13 / 12)
    assert scored.loc["A", "factor_score"] > scored.loc["B", "factor_score"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同定义和行情版本不能重复运行回测。"""
    for path in [
        tmp_path / "daily_adj_19901219_20260615.duckdb",
        tmp_path / "data" / "live_market_increment.duckdb",
    ]:
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
