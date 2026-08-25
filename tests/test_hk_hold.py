"""北向持仓缓存、点时门面和因子测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.hk_hold import (
    HkHoldDuckDBStore,
    attach_hk_hold_database,
    create_hk_hold_signal_dates,
    load_hk_hold_change_snapshot,
    materialize_hk_hold_change_asof,
    normalize_hk_hold_frame,
    update_hk_hold_month_ends,
)
from factors.hk_hold_change import score_hk_hold_change_frame


def _snapshot(
    trade_date: str,
    rows: list[tuple[str, float]],
) -> pd.DataFrame:
    """构造标准北向持仓快照。"""
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "ts_code": symbol,
                "name": symbol,
                "vol": 1000.0,
                "ratio": ratio,
                "exchange": "SZ",
            }
            for symbol, ratio in rows
        ]
    )


def test_normalize_filters_wrong_date_and_invalid_ratio() -> None:
    """请求日错配及非法持仓比例不得写入缓存。"""
    frame = pd.concat(
        [
            _snapshot("20230131", [("A.SZ", 1.0)]),
            _snapshot("20230201", [("B.SZ", 2.0)]),
            _snapshot("20230131", [("C.SZ", 101.0)]),
        ],
        ignore_index=True,
    )

    result = normalize_hk_hold_frame(frame, "20230131")

    assert result["ts_code"].tolist() == ["A.SZ"]


def test_updater_caches_empty_dates_and_skips_repeated_calls(
    tmp_path: Path,
) -> None:
    """空结果也要登记完成，防止每日任务反复调用外部接口。"""

    class Client:
        calls: list[str] = []

        def hk_hold(self, trade_date: str) -> pd.DataFrame:
            self.calls.append(trade_date)
            if trade_date == "20230131":
                return _snapshot(trade_date, [("A.SZ", 1.0)])
            return pd.DataFrame()

    client = Client()
    store = HkHoldDuckDBStore(tmp_path / "hk_hold.duckdb")

    first = update_hk_hold_month_ends(
        client,
        store,
        ["20230131", "20230228"],
    )
    second = update_hk_hold_month_ends(
        client,
        store,
        ["20230131", "20230228"],
    )

    assert first.api_calls == 2
    assert first.empty_dates == 1
    assert second.api_calls == 0
    assert second.skipped_dates == 2
    assert client.calls == ["20230131", "20230228"]


def test_asof_uses_two_visible_month_ends_and_does_not_fill_absence(
    tmp_path: Path,
) -> None:
    """只比较相邻两期都出现的股票，并阻断信号日后的快照。"""
    store = HkHoldDuckDBStore(tmp_path / "hk_hold.duckdb")
    store.upsert_snapshot(
        "20230131",
        _snapshot("20230131", [("A.SZ", 1.0), ("C.SZ", 3.0)]),
    )
    store.upsert_snapshot(
        "20230228",
        _snapshot("20230228", [("A.SZ", 1.8), ("B.SZ", 2.0)]),
    )
    store.upsert_snapshot(
        "20230331",
        _snapshot("20230331", [("A.SZ", 9.0)]),
    )
    connection = duckdb.connect()
    try:
        create_hk_hold_signal_dates(connection, ["20230228"])
        attach_hk_hold_database(connection, store.path)
        materialize_hk_hold_change_asof(connection)
        result = load_hk_hold_change_snapshot(connection)
    finally:
        connection.close()

    assert result["symbol"].tolist() == ["A.SZ"]
    assert result.iloc[0]["current_trade_date"] == "20230228"
    assert result.iloc[0]["prior_trade_date"] == "20230131"
    assert result.iloc[0]["holding_ratio_change"] == pytest.approx(0.8)


def test_factor_prefers_larger_ownership_increase() -> None:
    """连续披露股票中，持仓占比增幅更大者得分更高。"""
    frame = pd.DataFrame(
        {
            "symbol": ["INCREASE", "DECREASE"],
            "holding_ratio_change": [0.8, -0.5],
            "current_holding_ratio": [2.0, 1.0],
            "prior_holding_ratio": [1.2, 1.5],
            "period_gap_days": [28, 28],
        }
    )

    scored = score_hk_hold_change_frame(frame).set_index("symbol")

    assert scored.index.tolist() == ["INCREASE"]
    assert scored.loc["INCREASE", "factor_score"] == pytest.approx(1.0)
