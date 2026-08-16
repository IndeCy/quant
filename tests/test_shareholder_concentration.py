"""股东户数筹码集中研究测试。"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.shareholder_count import (
    attach_shareholder_count_database,
    create_shareholder_signal_date_table,
    load_shareholder_concentration_snapshot,
    materialize_shareholder_concentration_asof,
    normalize_shareholder_events,
    update_shareholder_count_cache,
)
from examples import shareholder_concentration_study as study
from factors.shareholder_concentration import (
    score_shareholder_concentration_frame,
)


class FakeShareholderClient:
    """模拟分页接口，第二页只返回一条。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stk_holdernumber(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(dict(kwargs))
        if int(kwargs["offset"]) == 0:
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": "20200110",
                        "end_date": "20191231",
                        "holder_num": 1000,
                    },
                    {
                        "ts_code": "DROP",
                        "ann_date": "20200111",
                        "end_date": "20191231",
                        "holder_num": None,
                    },
                ]
            )
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20200120",
                    "end_date": "20200120",
                    "holder_num": 900,
                }
            ]
        )


def test_shareholder_cache_paginates_cleans_and_persists(tmp_path: Path) -> None:
    """接口分页、空户数过滤和本地幂等落盘应同时生效。"""
    client = FakeShareholderClient()
    database = tmp_path / "shareholder.duckdb"

    result = update_shareholder_count_cache(
        client,
        database,
        start_date="20200101",
        end_date="20200131",
        force_full=True,
        page_size=2,
    )

    assert result.api_calls == 2
    assert result.fetched_rows == 2
    assert result.stored_rows == 2
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            "SELECT ts_code, ann_date, end_date, holder_num "
            "FROM shareholder_count_events ORDER BY ann_date"
        ).fetchall()
    assert rows == [
        ("000001.SZ", "20200110", "20191231", 1000),
        ("000001.SZ", "20200120", "20200120", 900),
    ]


def test_normalize_shareholder_events_handles_timestamp_and_bad_rows() -> None:
    """时间戳公告日应归一化，未来报告期和空值必须剔除。"""
    frame = pd.DataFrame(
        [
            {
                "ts_code": "A",
                "ann_date": "2025-05-12 15:09:08",
                "end_date": "20250507",
                "holder_num": 1234,
            },
            {
                "ts_code": "B",
                "ann_date": "20250101",
                "end_date": "20250102",
                "holder_num": 100,
            },
        ]
    )

    result = normalize_shareholder_events(frame)

    assert result["ts_code"].tolist() == ["A"]
    assert result.iloc[0]["ann_date"] == "20250512"


def test_shareholder_asof_uses_latest_visible_revision(tmp_path: Path) -> None:
    """同一报告期修订只能在新公告日后生效。"""
    database = tmp_path / "shareholder.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        """
        CREATE TABLE shareholder_count_events(
            ts_code VARCHAR,
            ann_date VARCHAR,
            end_date VARCHAR,
            holder_num BIGINT,
            source VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO shareholder_count_events VALUES (?, ?, ?, ?, 'fixture')",
        [
            ("A", "20200110", "20191231", 1000),
            ("A", "20200420", "20200331", 800),
            ("A", "20200510", "20200331", 750),
            ("A", "20200810", "20200630", 700),
            ("B", "20200110", "20191231", 1000),
            ("B", "20200420", "20200331", 1200),
        ],
    )
    connection.close()

    memory = duckdb.connect()
    try:
        create_shareholder_signal_date_table(memory, ["20200430", "20200531"])
        attach_shareholder_count_database(memory, database)
        materialize_shareholder_concentration_asof(memory)
        snapshot = load_shareholder_concentration_snapshot(memory)
    finally:
        memory.close()

    indexed = snapshot.set_index(["signal_date", "symbol"])
    april = indexed.loc[("20200430", "A")]
    may = indexed.loc[("20200531", "A")]
    assert april["latest_holder_num"] == pytest.approx(800)
    assert may["latest_holder_num"] == pytest.approx(750)
    assert april["concentration_rate_90d"] == pytest.approx(
        -math.log(0.8) * 90 / 91
    )
    assert indexed.loc[("20200430", "B")]["concentration_rate_90d"] < 0


def test_shareholder_factor_prefers_faster_concentration() -> None:
    """股东户数下降更快的股票应获得更高分。"""
    frame = pd.DataFrame(
        {
            "symbol": ["FAST", "SLOW", "DISPERSE"],
            "concentration_rate_90d": [0.30, 0.05, -0.10],
        }
    )

    result = score_shareholder_concentration_frame(frame).set_index("symbol")

    assert result.loc["FAST", "factor_score"] > result.loc["SLOW", "factor_score"]
    assert (
        result.loc["SLOW", "factor_score"]
        > result.loc["DISPERSE", "factor_score"]
    )


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同缓存、行情版本和定义不得重复回测。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")
    (data_dir / "shareholder_count_increment.duckdb").write_bytes(b"holder")

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
