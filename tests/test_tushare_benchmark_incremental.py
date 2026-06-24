"""Tushare ETF与指数基准增量缓存测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.tushare_benchmark_incremental import BenchmarkIncrementalStore, TushareBenchmarkUpdater


class FakeBenchmarkClient:
    """测试用基准行情客户端。"""

    def fund_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": "20260618",
                    "open": 4.8,
                    "high": 4.9,
                    "low": 4.7,
                    "close": 4.85,
                    "pre_close": 4.8,
                    "change": 0.05,
                    "pct_chg": 1.0,
                    "vol": 100.0,
                    "amount": 1000.0,
                }
            ]
        )

    def fund_adj(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame([{"ts_code": ts_code, "trade_date": "20260618", "adj_factor": 1.2}])

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": "20260618",
                    "open": 3000.0,
                    "high": 3010.0,
                    "low": 2990.0,
                    "close": 3005.0,
                    "pre_close": 3000.0,
                    "change": 5.0,
                    "pct_chg": 0.16,
                    "vol": 200.0,
                    "amount": 3000.0,
                }
            ]
        )


def test_benchmark_store_upserts_fund_and_index_rows(tmp_path: Path) -> None:
    """ETF行情、ETF复权因子和指数行情应分别幂等缓存。"""
    store = BenchmarkIncrementalStore(tmp_path / "benchmark.duckdb")
    client = FakeBenchmarkClient()

    store.upsert_fund(client.fund_daily("510300.SH", "20260618", "20260618"))
    store.upsert_fund_adj(client.fund_adj("510300.SH", "20260618", "20260618"))
    store.upsert_index(client.index_daily("000001.SH", "20260618", "20260618"))
    store.upsert_fund(client.fund_daily("510300.SH", "20260618", "20260618"))

    assert store.latest_date("fund_daily", "510300.SH") == "20260618"
    assert store.latest_date("fund_adj", "510300.SH") == "20260618"
    assert store.latest_date("index_daily", "000001.SH") == "20260618"
    assert store.count_rows("fund_daily") == 1


def test_benchmark_updater_uses_base_latest_and_builds_curves(tmp_path: Path) -> None:
    """更新器应从基线后一天开始补，并能导出复权ETF与指数净值曲线。"""
    store = BenchmarkIncrementalStore(tmp_path / "benchmark.duckdb")
    updater = TushareBenchmarkUpdater(FakeBenchmarkClient(), store)

    result = updater.update(
        end_date="20260618",
        fund_base_latest={"510300.SH": "20260617"},
        index_base_latest={"000001.SH": "20260617"},
    )
    curves = store.load_curves()

    assert result.updated_symbols == ["510300.SH", "000001.SH"]
    assert curves["510300.SH"].iloc[0] == 1.0
    assert curves["000001.SH"].iloc[0] == 1.0
