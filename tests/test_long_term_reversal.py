"""长期反转点时特征、评分和研究门禁测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.long_term_reversal import materialize_long_term_reversal
from examples import long_term_reversal_feasibility_study as study
from factors.long_term_reversal import score_long_term_reversal_frame


def test_feature_uses_only_lagged_prices() -> None:
    """信号日收益必须来自两个历史滞后价格。"""
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE daily_adj_cache(
            ts_code VARCHAR,
            trade_date VARCHAR,
            close_qfq DOUBLE
        )
        """
    )
    rows = [
        ("000001.SZ", f"2024{i:04d}", float(i))
        for i in range(1, 9)
    ]
    connection.executemany("INSERT INTO daily_adj_cache VALUES (?, ?, ?)", rows)

    materialize_long_term_reversal(
        connection,
        long_lag=4,
        recent_lag=2,
        source_start="20240001",
        research_start="20240001",
    )
    result = connection.execute(
        """
        SELECT trade_date, close_recent_lag, close_long_lag, long_term_return
        FROM long_term_reversal_features
        ORDER BY trade_date
        """
    ).fetchall()

    assert result[0] == ("20240005", 3.0, 1.0, 2.0)
    assert result[-1] == ("20240008", 6.0, 4.0, 0.5)


def test_score_ranks_long_term_loser_highest() -> None:
    """长期历史收益最低的股票获得最高反转分数。"""
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "long_term_return": [-0.5, 0.1, 0.8],
        }
    )

    scored = score_long_term_reversal_frame(frame).set_index("symbol")

    assert scored.loc["A", "factor_score"] == 1.0
    assert scored.loc["C", "factor_score"] == pytest.approx(1 / 3)


def test_feasibility_keeps_missing_month_in_denominator() -> None:
    """没有候选的月份不能从覆盖率分母消失。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20240131"],
            "symbol": ["A"],
            "long_term_return": [-0.2],
            "factor_score": [1.0],
            "ret120": [0.1],
            "vol60": [0.02],
            "adv_rmb": [30_000_000.0],
        }
    )

    monthly = study.build_monthly_coverage(
        candidates,
        ["20240131", "20240229"],
    )

    assert monthly["candidate_count"].tolist() == [1, 0]


def test_same_fingerprint_reuses_without_market_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同运行指纹必须直接复用，不能重复扫描大表。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    increment = tmp_path / "data" / "live_market_increment.duckdb"
    increment.parent.mkdir(parents=True, exist_ok=True)
    increment.write_bytes(b"increment")

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
        lambda *args, **kwargs: pytest.fail("不应扫描市场数据"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["reused"] is True
