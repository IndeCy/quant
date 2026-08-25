"""平滑动量特征、评分与研究去重测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.smooth_momentum import (
    load_smooth_momentum_snapshot,
    materialize_smooth_momentum,
)
from examples import smooth_momentum_study as study
from factors.smooth_momentum import score_smooth_momentum_frame


def test_smooth_path_scores_above_single_jump_without_future_data() -> None:
    """相近涨幅下平滑路径应胜过单日跳涨，未来价格不得影响旧信号。"""
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE daily_adj_cache(ts_code VARCHAR, trade_date VARCHAR, "
        "close_qfq DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO daily_adj_cache VALUES (?, ?, ?)",
        [
            ("SMOOTH", "20200101", 100.0),
            ("SMOOTH", "20200102", 101.0),
            ("SMOOTH", "20200103", 102.0),
            ("SMOOTH", "20200104", 103.0),
            ("SMOOTH", "20200105", 103.0),
            ("SMOOTH", "20200106", 500.0),
            ("JUMP", "20200101", 100.0),
            ("JUMP", "20200102", 103.0),
            ("JUMP", "20200103", 103.0),
            ("JUMP", "20200104", 103.0),
            ("JUMP", "20200105", 103.0),
            ("JUMP", "20200106", 500.0),
        ],
    )
    materialize_smooth_momentum(
        connection,
        formation_window=4,
        skip_window=1,
        lookback_start="20200101",
        research_start="20200101",
    )
    result = load_smooth_momentum_snapshot(connection)
    connection.close()
    signal = result[result["trade_date"].eq("20200105")]
    scored = score_smooth_momentum_frame(signal).set_index("symbol")

    assert scored.loc["SMOOTH", "momentum_skip_recent"] == pytest.approx(0.03)
    assert scored.loc["JUMP", "momentum_skip_recent"] == pytest.approx(0.03)
    assert scored.loc["SMOOTH", "path_continuity"] == pytest.approx(1.0)
    assert scored.loc["JUMP", "path_continuity"] == pytest.approx(1 / 3)
    assert scored.loc["SMOOTH", "factor_score"] > scored.loc["JUMP", "factor_score"]


def test_factor_removes_non_positive_momentum() -> None:
    """非正中期收益不能进入平滑动量候选池。"""
    frame = pd.DataFrame(
        {
            "symbol": ["POSITIVE", "NEGATIVE"],
            "momentum_skip_recent": [0.10, -0.10],
            "path_continuity": [0.60, 0.60],
            "smooth_momentum": [0.06, -0.06],
        }
    )
    scored = score_smooth_momentum_frame(frame)

    assert scored["symbol"].tolist() == ["POSITIVE"]


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
