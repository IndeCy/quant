"""游资龙头识别测试。"""

import pandas as pd

from runtime.hot_money_leader import build_leader_stock_daily


def test_leader_engine_selects_one_unique_leader_per_mainline() -> None:
    """每条主线只能有一个唯一龙头。"""
    limit_rows = pd.DataFrame(
        [
            {"trade_date": "20260703", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 80.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 120.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000002.SZ", "name": "A2", "limit_type": "U", "amount": 60.0, "pct_chg": 10.0, "open_times": 1},
        ]
    )
    sector_map = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000002.SZ", "sector_name": "算力"},
        ]
    )
    sector_momentum = pd.DataFrame([{"trade_date": "20260706", "sector_name": "算力", "is_mainline": True}])

    result = build_leader_stock_daily(limit_rows, sector_momentum, sector_map)
    daily = result[result["trade_date"] == "20260706"]

    assert daily[daily["role"] == "LEADER"]["ts_code"].tolist() == ["000001.SZ"]
    assert daily[daily["role"] == "SECONDARY_LEADER"]["ts_code"].tolist() == ["000002.SZ"]
    assert int(daily[daily["ts_code"] == "000001.SZ"]["limit_streak"].iloc[0]) == 2


def test_leader_engine_filters_non_mainline_stocks() -> None:
    """非主线涨停股只能被标记为过滤对象。"""
    limit_rows = pd.DataFrame(
        [
            {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 100.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000009.SZ", "name": "Z1", "limit_type": "U", "amount": 90.0, "pct_chg": 10.0, "open_times": 0},
        ]
    )
    sector_map = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000009.SZ", "sector_name": "其他"},
        ]
    )
    sector_momentum = pd.DataFrame([{"trade_date": "20260706", "sector_name": "算力", "is_mainline": True}])

    result = build_leader_stock_daily(limit_rows, sector_momentum, sector_map)

    assert result[result["ts_code"] == "000009.SZ"]["role"].tolist() == ["FILTERED"]


def test_leader_streak_is_not_inflated_by_multi_sector_mapping() -> None:
    """同一股票映射多个概念时，股票自身连板数不能被概念展开重复计数。"""
    limit_rows = pd.DataFrame(
        [
            {"trade_date": "20260703", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 80.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 120.0, "pct_chg": 10.0, "open_times": 0},
        ]
    )
    sector_map = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000001.SZ", "sector_name": "机器人"},
        ]
    )
    sector_momentum = pd.DataFrame(
        [
            {"trade_date": "20260706", "sector_name": "算力", "is_mainline": True},
            {"trade_date": "20260706", "sector_name": "机器人", "is_mainline": True},
        ]
    )

    result = build_leader_stock_daily(limit_rows, sector_momentum, sector_map)
    daily = result[result["trade_date"] == "20260706"]

    assert daily["sector_name"].tolist() == ["机器人", "算力"]
    assert daily["limit_streak"].tolist() == [2, 2]
