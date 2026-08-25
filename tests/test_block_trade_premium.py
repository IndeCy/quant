"""大宗交易溢价数据与因子测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.block_trades import (
    attach_block_trade_database,
    create_block_trade_signal_date_table,
    load_block_trade_premium_snapshot,
    materialize_block_trade_premium_asof,
    normalize_block_trade_events,
    update_block_trade_cache,
)
from examples import block_trade_premium_study as study
from factors.block_trade_premium import score_block_trade_premium_frame


class FakeBlockTradeClient:
    """模拟两页数据，其中包含两笔字段完全相同的真实成交。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def block_trade(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(dict(kwargs))
        duplicate = _event("A", "20200110", 11.0, 100.0)
        if int(kwargs["offset"]) == 0:
            return pd.DataFrame([duplicate, duplicate])
        return pd.DataFrame([_event("B", "20200120", 9.0, 200.0)])


def test_block_trade_cache_preserves_duplicates_and_replaces_month(
    tmp_path: Path,
) -> None:
    """真实重复成交要保留，重复同步同一月份不得继续累加。"""
    client = FakeBlockTradeClient()
    database = tmp_path / "block_trade.duckdb"
    first = update_block_trade_cache(
        client,
        database,
        start_date="20200101",
        end_date="20200131",
        force_full=True,
        page_size=2,
    )
    second = update_block_trade_cache(
        client,
        database,
        start_date="20200101",
        end_date="20200131",
        force_full=True,
        page_size=2,
    )

    assert first.fetched_rows == 3
    assert first.stored_rows == 3
    assert second.stored_rows == 3
    with duckdb.connect(str(database), read_only=True) as connection:
        duplicate_count = connection.execute(
            "SELECT COUNT(*) FROM block_trade_events WHERE ts_code='A'"
        ).fetchone()[0]
    assert duplicate_count == 2


def test_normalize_block_trade_filters_nonpositive_price() -> None:
    """成交价、成交量或成交金额非正时必须丢弃。"""
    result = normalize_block_trade_events(
        pd.DataFrame(
            [
                _event("OK", "20200110", 10.0, 100.0),
                _event("BAD", "20200110", 0.0, 100.0),
            ]
        )
    )

    assert result["ts_code"].tolist() == ["OK"]


def test_block_trade_asof_uses_raw_close_and_amount_weighting(
    tmp_path: Path,
) -> None:
    """溢价必须相对未复权收盘价计算，并按成交金额聚合。"""
    database = tmp_path / "block_trade.duckdb"
    raw = pd.DataFrame(
        [
            _event("A", "20200110", 11.0, 100.0),
            _event("A", "20200120", 12.0, 300.0),
            _event("A", "20200210", 20.0, 100.0),
            _event("B", "20200120", 8.0, 200.0),
        ]
    )
    normalized = normalize_block_trade_events(raw)
    with duckdb.connect(str(database)) as connection:
        _create_event_table(connection)
        connection.register("batch", normalized)
        connection.execute("INSERT INTO block_trade_events SELECT *, now() FROM batch")

    memory = duckdb.connect()
    try:
        memory.execute(
            """
            CREATE TABLE features(
                symbol VARCHAR, trade_date VARCHAR, raw_close DOUBLE
            )
            """
        )
        memory.executemany(
            "INSERT INTO features VALUES (?, ?, ?)",
            [
                ("A", "20200110", 10.0),
                ("A", "20200120", 10.0),
                ("A", "20200210", 10.0),
                ("B", "20200120", 10.0),
            ],
        )
        create_block_trade_signal_date_table(memory, ["20200131", "20200229"])
        attach_block_trade_database(memory, database)
        materialize_block_trade_premium_asof(memory, lookback_days=60)
        snapshot = load_block_trade_premium_snapshot(memory)
    finally:
        memory.close()

    indexed = snapshot.set_index(["signal_date", "symbol"])
    assert indexed.loc[("20200131", "A")]["amount_weighted_premium"] == pytest.approx(
        0.175
    )
    assert indexed.loc[("20200131", "B")]["amount_weighted_premium"] == pytest.approx(
        -0.2
    )
    assert indexed.loc[("20200229", "A")]["latest_trade_date"] == "20200210"


def test_block_trade_factor_keeps_only_positive_premium() -> None:
    """折价成交不得进入正溢价组合，溢价越高排名越高。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW", "DISCOUNT"],
            "amount_weighted_premium": [0.12, 0.03, -0.15],
        }
    )

    result = score_block_trade_premium_frame(frame).set_index("symbol")

    assert set(result.index) == {"HIGH", "LOW"}
    assert result.loc["HIGH", "factor_score"] > result.loc["LOW", "factor_score"]


def test_research_reuses_same_fingerprint_without_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """同一缓存和研究定义必须复用历史结果。"""
    (tmp_path / "daily_adj_19901219_20260615.duckdb").write_bytes(b"base")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live_market_increment.duckdb").write_bytes(b"increment")
    (data_dir / "block_trade_increment.duckdb").write_bytes(b"block")

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
        lambda *args, **kwargs: pytest.fail("不应重新回测"),
    )

    result = study.run_study(study.RuntimePaths(tmp_path), "20260724")

    assert result["reused"] is True


def _event(
    symbol: str,
    trade_date: str,
    price: float,
    amount: float,
) -> dict[str, object]:
    """构造一笔完整大宗交易。"""
    return {
        "ts_code": symbol,
        "trade_date": trade_date,
        "price": price,
        "vol": 10.0,
        "amount": amount,
        "buyer": "买方",
        "seller": "卖方",
    }


def _create_event_table(connection: duckdb.DuckDBPyConnection) -> None:
    """创建与生产缓存一致的最小事件表。"""
    connection.execute(
        """
        CREATE TABLE block_trade_events(
            event_key VARCHAR, duplicate_ordinal INTEGER, ts_code VARCHAR,
            trade_date VARCHAR, price DOUBLE, vol DOUBLE, amount DOUBLE,
            buyer VARCHAR, seller VARCHAR, source VARCHAR,
            fetched_at TIMESTAMP
        )
        """
    )
