"""Tushare 全市场日线增量缓存测试。"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from data.tushare_incremental import IncrementalDuckDBStore, TushareDailyUpdater


class FakeTushareClient:
    """只返回固定交易日截面，验证不会逐只股票请求。"""

    def __init__(self) -> None:
        self.daily_dates: list[str] = []
        self.factor_dates: list[str] = []

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "cal_date": ["20260616", "20260617", "20260618", "20260619", "20260622"],
                "is_open": [1, 1, 1, 0, 1],
            }
        )

    def daily(self, trade_date: str) -> pd.DataFrame:
        self.daily_dates.append(trade_date)
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": [trade_date],
                "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
                "pre_close": [10.0], "change": [0.2], "pct_chg": [2.0],
                "vol": [1000.0], "amount": [10200.0],
            }
        )

    def adj_factor(self, trade_date: str) -> pd.DataFrame:
        self.factor_dates.append(trade_date)
        return pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": [trade_date], "adj_factor": [1.2]})


class FailingTradeCalClient(FakeTushareClient):
    """模拟 trade_cal 频控失败，验证会回退本地交易日历。"""

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
        raise RuntimeError("trade_cal rate limit")


def test_updater_fetches_only_closed_open_dates_and_is_idempotent(tmp_path: Path) -> None:
    client = FakeTushareClient()
    store = IncrementalDuckDBStore(tmp_path / "increment.duckdb")
    updater = TushareDailyUpdater(client, store, base_latest_date="20260615")

    first = updater.update_through("20260622", now=datetime(2026, 6, 22, 13, 30))
    second = updater.update_through("20260622", now=datetime(2026, 6, 22, 14, 0))

    assert first.updated_dates == ["20260616", "20260617", "20260618"]
    assert second.updated_dates == []
    assert client.daily_dates == ["20260616", "20260617", "20260618"]
    assert client.factor_dates == client.daily_dates
    assert store.count_rows("daily") == 3
    assert store.count_rows("adj_factor") == 3


def test_updater_accepts_current_date_after_market_close(tmp_path: Path) -> None:
    client = FakeTushareClient()
    store = IncrementalDuckDBStore(tmp_path / "increment.duckdb")
    updater = TushareDailyUpdater(client, store, base_latest_date="20260618")

    result = updater.update_through("20260622", now=datetime(2026, 6, 22, 16, 0))

    assert result.updated_dates == ["20260622"]
    assert result.daily_rows == 1
    assert result.factor_rows == 1


def test_updater_falls_back_to_local_calendar_when_trade_cal_is_limited(tmp_path: Path) -> None:
    client = FailingTradeCalClient()
    store = IncrementalDuckDBStore(tmp_path / "increment.duckdb")
    updater = TushareDailyUpdater(client, store, base_latest_date="20260617")

    result = updater.update_through("20260624", now=datetime(2026, 6, 24, 11, 0))

    assert result.updated_dates == ["20260618", "20260622", "20260623"]
    assert client.daily_dates == result.updated_dates
    assert client.factor_dates == result.updated_dates
