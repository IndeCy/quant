"""Tushare beta 观测数据增量缓存测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.tushare_beta_incremental import BetaIncrementalStore, TushareBetaUpdater


class FakeBetaClient:
    """测试用 beta 数据客户端，避免单测访问真实 Tushare。"""

    def __init__(self) -> None:
        self.fund_share_requests: list[tuple[str, str, str]] = []

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000001.SZ",
                    "pe_ttm": 8.0,
                    "pb": 0.8,
                    "dv_ttm": 3.2,
                    "total_mv": 1000.0,
                    "circ_mv": 800.0,
                    "turnover_rate": 1.1,
                }
            ]
        )

    def index_dailybasic(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000300.SH",
                    "pe_ttm": 12.0,
                    "pb": 1.2,
                    "turnover_rate": 0.8,
                    "total_mv": 50000.0,
                }
            ]
        )

    def fund_share(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.fund_share_requests.append((ts_code, start_date, end_date))
        return pd.DataFrame([{"trade_date": end_date, "ts_code": ts_code, "fd_share": 123.0}])

    def moneyflow_hsgt(self, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": end_date,
                    "north_money": 20.0,
                    "south_money": 10.0,
                    "hgt": 8.0,
                    "sgt": 12.0,
                }
            ]
        )

    def margin(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "exchange_id": "SSE",
                    "rzye": 100.0,
                    "rzmre": 5.0,
                    "rqye": 20.0,
                    "rzrqye": 120.0,
                }
            ]
        )

    def margin_detail(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000001.SZ",
                    "rzye": 1.0,
                    "rqye": 0.2,
                    "rzmre": 0.3,
                    "rqmcl": 0.1,
                    "rzrqye": 1.2,
                }
            ]
        )


def test_beta_store_upserts_p0_tables_idempotently(tmp_path: Path) -> None:
    """P0 beta 表应按业务主键幂等覆盖，避免重复放大资金和估值信号。"""
    store = BetaIncrementalStore(tmp_path / "beta.duckdb")
    client = FakeBetaClient()

    store.upsert_daily_basic(client.daily_basic("20260710"))
    store.upsert_daily_basic(client.daily_basic("20260710"))
    store.upsert_index_dailybasic(client.index_dailybasic("20260710"))
    store.upsert_fund_share(client.fund_share("510300.SH", "20260710", "20260710"))
    store.upsert_moneyflow_hsgt(client.moneyflow_hsgt("20260710", "20260710"))
    store.upsert_margin(client.margin("20260710"))
    store.upsert_margin_detail(client.margin_detail("20260710"))

    assert store.count_rows("daily_basic") == 1
    assert store.count_rows("index_dailybasic") == 1
    assert store.count_rows("fund_share") == 1
    assert store.count_rows("moneyflow_hsgt") == 1
    assert store.count_rows("margin") == 1
    assert store.count_rows("margin_detail") == 1


def test_beta_updater_fetches_all_p0_sources(tmp_path: Path) -> None:
    """更新器应一次补齐单日 P0 beta 数据，供每日流水线复用。"""
    store = BetaIncrementalStore(tmp_path / "beta.duckdb")
    client = FakeBetaClient()
    updater = TushareBetaUpdater(client, store, fund_symbols=["510300.SH"])

    result = updater.update("20260710")

    assert result.trade_date == "20260710"
    assert result.daily_basic_rows == 1
    assert result.index_dailybasic_rows == 1
    assert result.fund_share_rows == 1
    assert result.moneyflow_hsgt_rows == 1
    assert result.margin_rows == 1
    assert result.margin_detail_rows == 1
    assert client.fund_share_requests == [("510300.SH", "20260626", "20260710")]


def test_beta_updater_covers_portfolio_funds_without_duplicates(tmp_path: Path) -> None:
    """ETF 份额应覆盖组合标的，并用短窗口吸收源端延迟与订正。"""
    client = FakeBetaClient()
    updater = TushareBetaUpdater(
        client,
        BetaIncrementalStore(tmp_path / "beta.duckdb"),
        fund_symbols=["518880.SH", "511010.SH", "518880.SH"],
    )

    updater.update("20260710")

    assert client.fund_share_requests == [
        ("511010.SH", "20260626", "20260710"),
        ("518880.SH", "20260626", "20260710"),
    ]
