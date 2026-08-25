"""订单规模资金流缓存、点时聚合和因子测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data.order_flow import (
    attach_order_flow_database,
    create_order_flow_signal_dates,
    materialize_large_order_flow_asof,
    normalize_order_flow,
    update_order_flow_cache,
)
from factors.large_order_flow import score_large_order_flow_frame
from factors.source_net_moneyflow import score_source_net_moneyflow_frame


class FakeOrderFlowClient:
    """提供正常日和合法空日。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        self.calls.append(trade_date)
        if trade_date == "20240103":
            return pd.DataFrame(columns=_raw(trade_date).keys())
        return pd.DataFrame([_raw(trade_date)])


def test_normalize_computes_compact_auditable_amounts() -> None:
    """原始八类金额必须压缩成可复核的净额和总额。"""
    result = normalize_order_flow(
        pd.DataFrame([_raw("20240102")]),
        "20240102",
    )

    row = result.iloc[0]
    assert row["large_net_amount_wan"] == pytest.approx(40.0)
    assert row["all_net_amount_wan"] == pytest.approx(50.0)
    assert row["classified_amount_wan"] == pytest.approx(150.0)
    assert row["source_net_amount_wan"] == pytest.approx(50.0)


def test_cache_resumes_and_accepts_empty_trade_date(tmp_path: Path) -> None:
    """合法空日也完成同步，重复运行不得再次请求。"""
    client = FakeOrderFlowClient()
    database = tmp_path / "order_flow.duckdb"
    dates = ["20240102", "20240103"]

    first = update_order_flow_cache(client, database, dates)
    second = update_order_flow_cache(client, database, dates)

    assert first.success is True
    assert first.fetched_dates == 2
    assert first.stored_rows == 1
    assert second.skipped_dates == 2
    assert len(client.calls) == 2


def test_asof_uses_twenty_real_trading_days_and_blocks_future(
    tmp_path: Path,
) -> None:
    """窗口按真实交易日推进，信号日后数据不可见。"""
    database = tmp_path / "order_flow.duckdb"
    client = FakeOrderFlowClient()
    dates = pd.bdate_range("2024-01-01", periods=22).strftime("%Y%m%d").tolist()
    update_order_flow_cache(client, database, dates)

    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TABLE features(symbol VARCHAR, trade_date VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO features VALUES (?, ?)",
            [("000001.SZ", value) for value in dates],
        )
        create_order_flow_signal_dates(connection, [dates[19]])
        attach_order_flow_database(connection, database)
        materialize_large_order_flow_asof(connection)
        result = connection.execute(
            "SELECT * FROM large_order_flow_asof"
        ).fetchdf()
    finally:
        connection.close()

    row = result.iloc[0]
    assert row["observations"] == 19
    assert row["latest_flow_date"] == dates[19]
    assert row["large_order_net_share"] == pytest.approx(40.0 / 150.0)
    assert row["source_net_turnover_share"] == pytest.approx(2 * 50.0 / 150.0)


def test_factor_requires_positive_flow_and_fifteen_observations() -> None:
    """负向资金流或观测不足不得进入横截面排名。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW", "NEGATIVE", "SPARSE"],
            "large_order_net_share": [0.2, 0.05, -0.1, 0.5],
            "observations": [20, 20, 20, 14],
        }
    )

    result = score_large_order_flow_frame(frame).set_index("symbol")

    assert set(result.index) == {"HIGH", "LOW"}
    assert result.loc["HIGH", "factor_score"] > result.loc[
        "LOW", "factor_score"
    ]


def test_source_net_factor_uses_vendor_net_flow_not_symmetric_bucket_sum() -> None:
    """V2必须读取源净流入占比，不能退回恒近零的全档买卖差。"""
    frame = pd.DataFrame(
        {
            "symbol": ["HIGH", "LOW", "NEGATIVE"],
            "source_net_turnover_share": [0.20, 0.05, -0.10],
            "observations": [20, 20, 20],
        }
    )

    result = score_source_net_moneyflow_frame(frame).set_index("symbol")

    assert set(result.index) == {"HIGH", "LOW"}
    assert result.loc["HIGH", "factor_score"] > result.loc[
        "LOW", "factor_score"
    ]


def _raw(trade_date: str) -> dict[str, object]:
    """构造一行完整资金流分类数据。"""
    return {
        "trade_date": trade_date,
        "ts_code": "000001.SZ",
        "buy_sm_amount": 10.0,
        "sell_sm_amount": 5.0,
        "buy_md_amount": 20.0,
        "sell_md_amount": 15.0,
        "buy_lg_amount": 30.0,
        "sell_lg_amount": 10.0,
        "buy_elg_amount": 40.0,
        "sell_elg_amount": 20.0,
        "net_mf_amount": 50.0,
    }
