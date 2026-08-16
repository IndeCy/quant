"""重要股东净增持研究测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.holder_trades import (
    attach_holder_trade_database,
    create_holder_trade_signal_date_table,
    load_holder_trade_snapshot,
    materialize_holder_trade_asof,
    normalize_holder_trade_events,
    update_holder_trade_cache,
)
from examples import insider_net_buying_study as study
from factors.insider_net_buying import score_insider_net_buying_frame


EVENT_COLUMNS = [
    "ts_code",
    "ann_date",
    "holder_name",
    "holder_type",
    "in_de",
    "change_vol",
    "change_ratio",
    "after_share",
    "after_ratio",
    "avg_price",
    "total_share",
    "begin_date",
    "close_date",
]


class FakeHolderTradeClient:
    """模拟带分页的 Tushare 增减持接口。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def stk_holdertrade(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(dict(kwargs))
        offset = int(kwargs["offset"])
        if offset == 0:
            return pd.DataFrame(
                [
                    _event("A", "20200110", "高管甲", "G", "IN", 0.5),
                    _event("DROP", "20200111", "无比例", "P", "IN", None),
                ]
            )
        return pd.DataFrame(
            [_event("B", "20200120", "股东乙", "P", "DE", 0.2)]
        )


def test_holder_trade_cache_paginates_and_filters_invalid_rows(tmp_path: Path) -> None:
    """缓存应分页、过滤无比例事件并幂等落盘。"""
    database = tmp_path / "holder_trade.duckdb"
    result = update_holder_trade_cache(
        FakeHolderTradeClient(),
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
            "SELECT ts_code, in_de, change_ratio "
            "FROM holder_trade_events ORDER BY ts_code"
        ).fetchall()
    assert rows == [("A", "IN", 0.5), ("B", "DE", 0.2)]


def test_event_identity_keeps_revisions_of_same_plan_together() -> None:
    """同一持有人同一计划的后续公告应保留相同事件身份。"""
    frame = pd.DataFrame(
        [
            _event(
                "A",
                "20200110",
                "高管甲",
                "G",
                "IN",
                0.2,
                begin_date="20191201",
                close_date="20200101",
            ),
            _event(
                "A",
                "20200210",
                "高管甲",
                "G",
                "IN",
                0.5,
                begin_date="20191201",
                close_date="20200201",
            ),
        ]
    )

    normalized = normalize_holder_trade_events(frame)

    assert normalized["event_key"].nunique() == 1
    assert normalized["ann_date"].tolist() == ["20200110", "20200210"]


def test_holder_trade_asof_uses_latest_revision_and_excludes_company(
    tmp_path: Path,
) -> None:
    """截面只能使用已公告修订，并排除公司账户交易。"""
    database = tmp_path / "holder_trade.duckdb"
    raw = pd.DataFrame(
        [
            _event(
                "A", "20200110", "高管甲", "G", "IN", 0.2, begin_date="20191201"
            ),
            _event(
                "A", "20200210", "高管甲", "G", "IN", 0.5, begin_date="20191201"
            ),
            _event("A", "20200120", "股东乙", "P", "DE", 0.1),
            _event("A", "20200120", "回购账户", "C", "IN", 9.0),
            _event("B", "20190101", "过期股东", "P", "IN", 1.0),
        ]
    )
    normalized = normalize_holder_trade_events(raw)
    with duckdb.connect(str(database)) as connection:
        _create_fixture_table(connection)
        connection.register("batch", normalized)
        connection.execute(
            "INSERT INTO holder_trade_events SELECT *, now() FROM batch"
        )

    memory = duckdb.connect()
    try:
        create_holder_trade_signal_date_table(memory, ["20200131", "20200229"])
        attach_holder_trade_database(memory, database)
        materialize_holder_trade_asof(memory, lookback_days=180)
        snapshot = load_holder_trade_snapshot(memory)
    finally:
        memory.close()

    indexed = snapshot.set_index(["signal_date", "symbol"])
    assert indexed.loc[("20200131", "A")]["net_buy_ratio"] == pytest.approx(0.1)
    assert indexed.loc[("20200229", "A")]["net_buy_ratio"] == pytest.approx(0.4)
    assert "B" not in snapshot["symbol"].tolist()
    assert indexed.loc[("20200229", "A")]["buy_event_count"] == 1


def test_insider_net_buying_factor_keeps_positive_and_ranks_strength() -> None:
    """净减持股票不得入选，净增持比例更高者得分更高。"""
    frame = pd.DataFrame(
        {
            "symbol": ["STRONG", "WEAK", "SELL"],
            "net_buy_ratio": [1.2, 0.2, -0.5],
        }
    )

    result = score_insider_net_buying_frame(frame).set_index("symbol")

    assert set(result.index) == {"STRONG", "WEAK"}
    assert result.loc["STRONG", "factor_score"] > result.loc["WEAK", "factor_score"]


def test_research_reuses_same_fingerprint_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """相同缓存、行情版本和定义不得重复执行回测。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")
    (data_dir / "holder_trade_increment.duckdb").write_bytes(b"holder")

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


def _event(
    symbol: str,
    ann_date: str,
    holder_name: str,
    holder_type: str,
    direction: str,
    ratio: float | None,
    *,
    begin_date: str | None = "20191201",
    close_date: str | None = "20200101",
) -> dict[str, object]:
    """构造完整的最小增减持事件。"""
    return {
        "ts_code": symbol,
        "ann_date": ann_date,
        "holder_name": holder_name,
        "holder_type": holder_type,
        "in_de": direction,
        "change_vol": 100.0,
        "change_ratio": ratio,
        "after_share": 1000.0,
        "after_ratio": 1.0,
        "avg_price": 10.0,
        "total_share": 1000.0,
        "begin_date": begin_date,
        "close_date": close_date,
    }


def _create_fixture_table(connection: duckdb.DuckDBPyConnection) -> None:
    """创建与生产缓存一致的测试表。"""
    connection.execute(
        """
        CREATE TABLE holder_trade_events (
            event_key VARCHAR, ts_code VARCHAR, ann_date VARCHAR,
            holder_name VARCHAR, holder_type VARCHAR, in_de VARCHAR,
            change_vol DOUBLE, change_ratio DOUBLE, after_share DOUBLE,
            after_ratio DOUBLE, avg_price DOUBLE, total_share DOUBLE,
            begin_date VARCHAR, close_date VARCHAR, source VARCHAR,
            fetched_at TIMESTAMP
        )
        """
    )
