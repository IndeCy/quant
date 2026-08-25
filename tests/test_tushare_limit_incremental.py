from pathlib import Path

import pandas as pd

from data.tushare_limit_incremental import LimitListDuckDBStore, update_limit_list_range


class FakeLimitClient:
    """测试用涨跌停客户端，避免单测访问真实 Tushare。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def limit_list_d(self, trade_date: str) -> pd.DataFrame:
        self.calls.append(trade_date)
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "ts_code": "000001.SZ",
                    "name": "样本A",
                    "close": 10.0,
                    "pct_chg": 10.0,
                    "limit": "U",
                    "amount": 1_000_000.0,
                    "fd_amount": 500_000.0,
                    "first_time": "093000",
                    "last_time": "145700",
                    "open_times": 0,
                },
                {
                    "trade_date": trade_date,
                    "ts_code": "000002.SZ",
                    "name": "样本B",
                    "close": 8.0,
                    "pct_chg": -10.0,
                    "limit": "D",
                    "amount": 900_000.0,
                    "fd_amount": 300_000.0,
                    "first_time": None,
                    "last_time": "092500",
                    "open_times": 0,
                },
            ]
        )


def test_update_limit_list_range_writes_standard_rows(tmp_path: Path) -> None:
    store = LimitListDuckDBStore(tmp_path / "limit_list.duckdb")
    client = FakeLimitClient()

    result = update_limit_list_range(store, client, ["20260707"])

    rows = store.load("20260707", "20260707")
    assert result["rows_written"] == 2
    assert client.calls == ["20260707"]
    assert rows["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]
    assert rows["limit_type"].tolist() == ["U", "D"]


def test_update_limit_list_range_is_idempotent(tmp_path: Path) -> None:
    store = LimitListDuckDBStore(tmp_path / "limit_list.duckdb")
    client = FakeLimitClient()

    update_limit_list_range(store, client, ["20260707"])
    update_limit_list_range(store, client, ["20260707"])

    rows_after_second_update = store.load("20260707", "20260707")
    assert len(rows_after_second_update) == 2
