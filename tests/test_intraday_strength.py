"""隔夜与日内收益分解的特征、评分和研究去重测试。"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.intraday_return import (
    load_intraday_strength_snapshot,
    materialize_intraday_strength,
)
from examples import intraday_strength_study as study
from factors.intraday_strength import score_intraday_strength_frame


def test_return_decomposition_is_future_free_and_reconstructs_total() -> None:
    """20日分解只能使用当日及此前行情，并应还原完整区间收益。"""
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, "
        "open_qfq DOUBLE, close_qfq DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?, ?)",
        [
            ("A", "20200101", 10.0, 11.0),
            ("A", "20200102", 12.0, 12.0),
            ("A", "20200103", 11.0, 13.0),
            ("A", "20200104", 100.0, 100.0),
        ],
    )
    materialize_intraday_strength(
        connection,
        window=2,
        lookback_start="20200101",
        research_start="20200101",
    )
    result = load_intraday_strength_snapshot(connection).set_index("trade_date")
    connection.close()

    # 1月3日两日完整收益应为 13 / 11 - 1，不能读到1月4日。
    assert result.loc["20200103", "decomposed_total_return"] == pytest.approx(
        13 / 11 - 1
    )
    expected_strength = sum(math.log(value) for value in [12 / 12, 13 / 11])
    expected_strength -= sum(math.log(value) for value in [12 / 11, 11 / 12])
    assert result.loc["20200103", "intraday_strength"] == pytest.approx(
        expected_strength
    )


def test_factor_prefers_stronger_intraday_relative_to_overnight() -> None:
    """更强的日内相对收益必须得到更高分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["STRONG", "WEAK", "INVALID"],
            "intraday_strength": [0.20, -0.10, float("inf")],
        }
    )
    scored = score_intraday_strength_frame(frame).set_index("symbol")

    assert set(scored.index) == {"STRONG", "WEAK"}
    assert scored.loc["STRONG", "factor_score"] > scored.loc["WEAK", "factor_score"]


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
