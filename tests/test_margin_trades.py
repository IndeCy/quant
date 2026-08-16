"""融资融券增量缓存与可见性覆盖测试。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from data.margin_trades import normalize_margin_detail, update_margin_trade_cache
from examples import margin_flow_data_feasibility_study as study


def _row(trade_date: str, ts_code: str = "000001.SZ") -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "ts_code": ts_code,
        "rzye": 100.0,
        "rqye": 2.0,
        "rzmre": 10.0,
        "rqyl": 1.0,
        "rzche": 4.0,
        "rqchl": 0.0,
        "rqmcl": 0.0,
        "rzrqye": 102.0,
    }


def test_margin_cache_resumes_and_skips_successful_dates(tmp_path: Path) -> None:
    """首次成功日期在第二次更新时不得重复请求。"""

    class Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def margin_detail(self, **kwargs: object) -> pd.DataFrame:
            trade_date = str(kwargs["trade_date"])
            self.calls.append(trade_date)
            return pd.DataFrame([_row(trade_date)])

    client = Client()
    path = tmp_path / "margin.duckdb"
    first = update_margin_trade_cache(client, path, ["20240102", "20240103"])
    second = update_margin_trade_cache(client, path, ["20240102", "20240103"])

    assert first.fetched_dates == 2
    assert second.skipped_dates == 2
    assert client.calls == ["20240102", "20240103"]
    with duckdb.connect(str(path), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM margin_detail").fetchone()[0] == 2


def test_margin_normalization_rejects_other_trade_date() -> None:
    """接口混入其他日期时不得污染请求日缓存。"""
    result = normalize_margin_detail(
        pd.DataFrame([_row("20240102"), _row("20240103", "000002.SZ")]),
        "20240102",
    )

    assert result[["trade_date", "ts_code"]].to_dict("records") == [
        {"trade_date": "20240102", "ts_code": "000001.SZ"}
    ]


def test_margin_feasibility_requires_locked_nonempty_months() -> None:
    """锁定期出现空候选月份时必须拒绝进入回测。"""
    daily = pd.DataFrame(
        {
            "trade_date": ["20220104", "20220105"],
            "row_count": [1000, 1000],
            "status": ["SUCCESS", "SUCCESS"],
        }
    )
    monthly = pd.DataFrame(
        {
            "signal_date": ["20220131", "20220228"],
            "valid_count": [1000, 1000],
            "positive_count": [200, 0],
        }
    )

    result = study.evaluate_feasibility(daily, monthly, "20220228")

    assert result["passed"] is False
    assert result["checks"]["locked_nonempty_share"] is False
