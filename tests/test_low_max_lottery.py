"""低 MAX 彩票偏好研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.lottery_features import (
    load_lottery_max_snapshot,
    materialize_lottery_max_features,
)
from examples import low_max_lottery_study as study
from factors.lottery_preference import score_low_max_frame


def test_lottery_max_requires_full_window_and_includes_signal_day() -> None:
    """只有完整20日样本才输出，信号日当天收益可参与计算。"""
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TEMP TABLE features(trade_date VARCHAR, symbol VARCHAR, ret DOUBLE)"
        )
        rows = [
            (
                f"202001{day:02d}",
                "000001.SZ",
                None if day == 1 else (0.18 if day == 21 else day / 1000),
            )
            for day in range(1, 22)
        ]
        connection.executemany("INSERT INTO features VALUES (?, ?, ?)", rows)
        materialize_lottery_max_features(connection, window=20)
        snapshot = load_lottery_max_snapshot(connection, window=20)
    finally:
        connection.close()

    assert snapshot["trade_date"].tolist() == ["20200121"]
    assert snapshot.iloc[0]["observations"] == 20
    assert snapshot.iloc[0]["max_ret20"] == pytest.approx(0.18)


def test_low_max_factor_prefers_stock_without_extreme_daily_jump() -> None:
    """近期最大单日涨幅更低的股票应获得更高分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["CALM", "LOTTERY", "MIDDLE"],
            "max_ret20": [0.03, 0.20, 0.08],
        }
    )

    result = score_low_max_frame(frame).set_index("symbol")

    assert result.loc["CALM", "factor_score"] > result.loc["MIDDLE", "factor_score"]
    assert (
        result.loc["MIDDLE", "factor_score"]
        > result.loc["LOTTERY", "factor_score"]
    )


def test_low_max_factor_rejects_missing_standard_column() -> None:
    """缺失 MAX 特征时必须显式失败。"""
    with pytest.raises(ValueError, match="max_ret20"):
        score_low_max_frame(pd.DataFrame({"symbol": ["A"]}))


def test_low_vol_diagnostics_measure_rank_and_topn_overlap() -> None:
    """归因指标应正确识别低MAX与低波完全一致的截面。"""
    candidates = pd.DataFrame(
        {
            "signal_date": ["20200131"] * 40,
            "symbol": [f"S{i:02d}" for i in range(40)],
            "max_ret20": list(range(40)),
            "vol60": list(range(40)),
        }
    )
    holdings = candidates.assign(rank=range(1, 41))

    result = study.build_low_vol_diagnostics(candidates, holdings)

    assert result["median_spearman_with_vol60"] == pytest.approx(1.0)
    assert result["latest_top40_overlap_with_lowvol"] == pytest.approx(1.0)


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同行情版本和研究定义不得重复回测。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")

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

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True
