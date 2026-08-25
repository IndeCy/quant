"""融资净买入强度点时门面和因子测试。"""

from __future__ import annotations

import duckdb
import pandas as pd

from data.margin_flow import (
    create_margin_signal_date_table,
    load_margin_flow_snapshot,
    materialize_margin_flow_asof,
)
from factors.margin_flow import score_margin_flow_frame


def test_margin_flow_uses_previous_trade_day_and_contiguous_window() -> None:
    """T 日信号必须只看到 T-1，缺少中间交易日的股票不能进入。"""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE features(
                trade_date VARCHAR, symbol VARCHAR, amount DOUBLE,
                amount_p20 DOUBLE, volume DOUBLE, close DOUBLE,
                st_name VARCHAR, is_suspended BOOLEAN
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE stock_basic(
                ts_code VARCHAR, list_date VARCHAR, delist_date VARCHAR
            )
            """
        )
        dates = ["20240102", "20240103", "20240104", "20240105"]
        feature_rows = [
            (date, symbol, 100.0, 10.0, 100.0, 10.0, None, False)
            for date in dates
            for symbol in ["AAA.SZ", "BBB.SZ"]
        ]
        connection.executemany(
            "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            feature_rows,
        )
        connection.executemany(
            "INSERT INTO stock_basic VALUES (?, ?, ?)",
            [("AAA.SZ", "20100101", None), ("BBB.SZ", "20100101", None)],
        )
        connection.execute("CREATE SCHEMA margin_db")
        connection.execute(
            """
            CREATE TABLE margin_db.margin_detail(
                trade_date VARCHAR, ts_code VARCHAR,
                rzmre DOUBLE, rzche DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO margin_db.margin_detail VALUES (?, ?, ?, ?)",
            [
                ("20240102", "AAA.SZ", 10.0, 1.0),
                ("20240103", "AAA.SZ", 11.0, 1.0),
                ("20240104", "AAA.SZ", 12.0, 1.0),
                ("20240102", "BBB.SZ", 10.0, 1.0),
                ("20240104", "BBB.SZ", 12.0, 1.0),
            ],
        )
        create_margin_signal_date_table(connection, ["20240105"])
        materialize_margin_flow_asof(connection, lookback_trading_days=3)
        snapshot = load_margin_flow_snapshot(connection)
    finally:
        connection.close()

    assert snapshot["symbol"].tolist() == ["AAA.SZ"]
    assert snapshot.iloc[0]["visible_through_date"] == "20240104"
    assert snapshot.iloc[0]["net_buy_20d"] == 30.0


def test_margin_flow_factor_keeps_only_positive_values() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "margin_flow_intensity": [0.02, -0.01, 0.01],
        }
    )

    result = score_margin_flow_frame(frame)

    assert result["symbol"].tolist() == ["A", "C"]
    assert result["factor_score"].tolist() == [1.0, 0.5]
