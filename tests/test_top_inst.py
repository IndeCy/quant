"""龙虎榜机构席位缓存、点时聚合与因子测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.top_inst import (
    attach_top_inst_database,
    create_top_inst_signal_dates,
    materialize_top_inst_flow_asof,
    normalize_top_inst_events,
    update_top_inst_cache,
)
from factors.top_inst_flow import score_top_inst_flow_frame


class FakeTopInstClient:
    """提供含榜单重复行和合法空日的模拟客户端。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        self.calls.append(trade_date)
        if trade_date == "20240103":
            return pd.DataFrame(columns=_raw("A", trade_date).keys())
        event = _raw("A", trade_date)
        return pd.DataFrame(
            [
                event,
                {**event, "side": "1"},
                {**event, "reason": "连续三日偏离"},
            ]
        )


def test_normalize_deduplicates_side_and_reason_rows() -> None:
    """同一席位成交进入多个榜单展示时只能计算一次。"""
    event = _raw("A", "20240102")
    raw = pd.DataFrame(
        [
            event,
            {**event, "side": "1"},
            {**event, "reason": "连续三日偏离"},
        ]
    )

    result = normalize_top_inst_events(raw, "20240102")

    assert len(result) == 1
    assert result.iloc[0]["source_row_count"] == 3
    assert result.iloc[0]["side_count"] == 2
    assert result.iloc[0]["reason_count"] == 2
    assert result.iloc[0]["net_buy"] == pytest.approx(60.0)


def test_cache_resumes_and_treats_empty_trade_date_as_success(
    tmp_path: Path,
) -> None:
    """无机构上榜是合法观测，重复同步不得再次请求。"""
    client = FakeTopInstClient()
    database = tmp_path / "top_inst.duckdb"
    dates = ["20240102", "20240103"]

    first = update_top_inst_cache(client, database, dates)
    second = update_top_inst_cache(client, database, dates)

    assert first.success is True
    assert first.fetched_dates == 2
    assert first.normalized_rows == 1
    assert second.skipped_dates == 2
    assert len(client.calls) == 2


def test_asof_uses_twenty_real_trading_days_and_blocks_future(
    tmp_path: Path,
) -> None:
    """20日窗口按交易日序号计算，信号日之后事件不可见。"""
    database = tmp_path / "top_inst.duckdb"
    client = FakeTopInstClient()
    trade_dates = pd.bdate_range("2024-01-01", periods=22).strftime("%Y%m%d").tolist()
    update_top_inst_cache(client, database, trade_dates)

    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TABLE features(symbol VARCHAR, trade_date VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO features VALUES (?, ?)",
            [("A", value) for value in trade_dates],
        )
        create_top_inst_signal_dates(connection, [trade_dates[19]])
        attach_top_inst_database(connection, database)
        materialize_top_inst_flow_asof(connection)
        result = connection.execute(
            "SELECT * FROM top_inst_flow_asof"
        ).fetchdf()
    finally:
        connection.close()

    # 第3个交易日为空，因此前20个交易日只有19笔唯一成交。
    assert result.iloc[0]["unique_seat_events"] == 19
    assert result.iloc[0]["latest_event_date"] == trade_dates[19]
    assert result.iloc[0]["total_net_buy"] == pytest.approx(19 * 60.0)


def test_factor_normalizes_net_buy_by_liquidity_and_keeps_positive() -> None:
    """净买入按成交额归一化，净卖出股票不得进入候选池。"""
    frame = pd.DataFrame(
        {
            "symbol": ["STRONG", "WEAK", "SELL"],
            "total_net_buy": [100.0, 100.0, -100.0],
            "adv_rmb": [1_000.0, 10_000.0, 1_000.0],
        }
    )

    result = score_top_inst_flow_frame(frame).set_index("symbol")

    assert set(result.index) == {"STRONG", "WEAK"}
    assert result.loc["STRONG", "factor_score"] > result.loc[
        "WEAK", "factor_score"
    ]


def _raw(symbol: str, trade_date: str) -> dict[str, object]:
    """构造一条完整机构席位原始记录。"""
    return {
        "trade_date": trade_date,
        "ts_code": symbol if "." in symbol else "000001.SZ",
        "exalter": "机构专用",
        "side": "0",
        "buy": 100.0,
        "buy_rate": 10.0,
        "sell": 40.0,
        "sell_rate": 4.0,
        "net_buy": 60.0,
        "reason": "涨幅偏离",
    }
