"""唯一日常 Pipeline 的研究扩展数据增量测试。"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import duckdb
import pandas as pd

from data.holder_trades import HOLDER_TRADE_FIELDS
from data.order_flow import MONEYFLOW_FIELDS
from data.top_inst import TOP_INST_FIELDS
from runtime.daily_extension_data import (
    ExtensionDataClients,
    format_extension_sync_summary,
    resolve_missing_market_dates,
    sync_daily_extension_data,
)
from runtime.paths import RuntimePaths


class FakeExtensionClients:
    """覆盖全部扩展域的无网络客户端。"""

    def __init__(self) -> None:
        self.order_flow_dates: list[str] = []
        self.top_inst_dates: list[str] = []
        self.margin_dates: list[str] = []
        self.block_calls: list[dict[str, object]] = []
        self.shareholder_calls: list[dict[str, object]] = []
        self.holder_trade_calls: list[dict[str, object]] = []

    def moneyflow(self, trade_date: str) -> pd.DataFrame:
        self.order_flow_dates.append(trade_date)
        return pd.DataFrame(columns=MONEYFLOW_FIELDS)

    def top_inst(self, trade_date: str) -> pd.DataFrame:
        self.top_inst_dates.append(trade_date)
        return pd.DataFrame(columns=TOP_INST_FIELDS)

    def margin_detail(self, **kwargs: object) -> pd.DataFrame:
        trade_date = str(kwargs["trade_date"])
        self.margin_dates.append(trade_date)
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000001.SZ",
                    "rzye": 100.0,
                    "rqye": 2.0,
                    "rzmre": 10.0,
                    "rqyl": 1.0,
                    "rzche": 4.0,
                    "rqchl": 0.0,
                    "rqmcl": 0.0,
                    "rzrqye": 102.0,
                }
            ]
        )

    def block_trade(self, **kwargs: object) -> pd.DataFrame:
        self.block_calls.append(dict(kwargs))
        return pd.DataFrame(
            columns=["ts_code", "trade_date", "price", "vol", "amount", "buyer", "seller"]
        )

    def stk_holdernumber(self, **kwargs: object) -> pd.DataFrame:
        self.shareholder_calls.append(dict(kwargs))
        return pd.DataFrame(columns=["ts_code", "ann_date", "end_date", "holder_num"])

    def stk_holdertrade(self, **kwargs: object) -> pd.DataFrame:
        self.holder_trade_calls.append(dict(kwargs))
        return pd.DataFrame(columns=HOLDER_TRADE_FIELDS.split(","))


def test_missing_market_dates_prioritizes_latest_and_bounds_backfill(tmp_path: Path) -> None:
    """历史缺口很多时必须保留最新日，并限制单次请求预算。"""
    paths = _paths_with_market_dates(tmp_path)

    dates = resolve_missing_market_dates(
        paths,
        paths.order_flow_path,
        "order_flow_sync_log",
        "20240110",
        max_gap_dates=5,
    )

    assert dates == ["20240102", "20240103", "20240104", "20240105", "20240110"]


def test_daily_extension_sync_updates_six_domains_and_records_audit(tmp_path: Path) -> None:
    """扩展域在同一个 data-update 节点内更新，并统一记录同步运行。"""
    paths = _paths_with_market_dates(tmp_path)
    fake = FakeExtensionClients()
    clients = ExtensionDataClients(fake, fake, fake, fake, fake, fake)

    results = sync_daily_extension_data(
        paths,
        "20240110",
        "test-token",
        clients=clients,
        max_gap_dates=5,
    )

    expected_dates = ["20240102", "20240103", "20240104", "20240105", "20240110"]
    assert fake.order_flow_dates == expected_dates
    assert fake.top_inst_dates == expected_dates
    assert fake.margin_dates == expected_dates
    assert all(item.status == "SUCCESS" for item in results)
    assert fake.shareholder_calls[0]["limit"] == 3000
    assert "更新6域" in format_extension_sync_summary(results)
    with sqlite3.connect(paths.system_state_path) as con:
        rows = con.execute(
            "SELECT dataset_id, status FROM data_sync_runs ORDER BY dataset_id"
        ).fetchall()
    assert rows == [
        ("event.block_trade", "SUCCESS"),
        ("event.holder_trade", "SUCCESS"),
        ("event.shareholder_count", "SUCCESS"),
        ("flow.order", "SUCCESS"),
        ("flow.top_inst", "SUCCESS"),
        ("margin.detail", "SUCCESS"),
    ]


def test_extension_sync_continues_when_one_research_domain_is_unavailable(
    tmp_path: Path,
) -> None:
    """研究扩展接口无权限时只记录该域异常，不能打断其他数据域。"""
    paths = _paths_with_market_dates(tmp_path, dates=["20240110"])
    fake = FakeExtensionClients()

    class DeniedTopInst:
        def top_inst(self, trade_date: str) -> pd.DataFrame:
            raise PermissionError(f"top_inst unavailable for {trade_date}")

    clients = ExtensionDataClients(fake, DeniedTopInst(), fake, fake, fake, fake)

    results = sync_daily_extension_data(
        paths,
        "20240110",
        "test-token",
        clients=clients,
        max_gap_dates=1,
    )

    status = {item.dataset_id: item.status for item in results}
    assert status["flow.top_inst"] == "FAILED"
    assert status["flow.order"] == "SUCCESS"
    assert status["margin.detail"] == "SUCCESS"
    assert "1域未更新(flow.top_inst)" in format_extension_sync_summary(results)


def _paths_with_market_dates(
    tmp_path: Path,
    *,
    dates: list[str] | None = None,
) -> RuntimePaths:
    paths = RuntimePaths(tmp_path)
    paths.ensure_directories()
    values = dates or [
        "20240102",
        "20240103",
        "20240104",
        "20240105",
        "20240108",
        "20240109",
        "20240110",
    ]
    with duckdb.connect(str(paths.live_market_increment_path)) as con:
        con.execute("CREATE TABLE daily(trade_date VARCHAR, ts_code VARCHAR)")
        con.executemany(
            "INSERT INTO daily VALUES (?, '000001.SZ')",
            [(value,) for value in values],
        )
    return paths
