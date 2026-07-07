"""游资主线板块强度测试。"""

import pandas as pd

from runtime.hot_money_sector import build_sector_momentum_daily


def test_sector_momentum_selects_top_three_mainlines() -> None:
    """板块强度最多只应识别前三条主线。"""
    limit_rows = pd.DataFrame(
        [
            {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 100.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000002.SZ", "name": "A2", "limit_type": "U", "amount": 80.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000003.SZ", "name": "B1", "limit_type": "U", "amount": 70.0, "pct_chg": 10.0, "open_times": 1},
            {"trade_date": "20260706", "ts_code": "000004.SZ", "name": "C1", "limit_type": "U", "amount": 60.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000005.SZ", "name": "D1", "limit_type": "U", "amount": 50.0, "pct_chg": 10.0, "open_times": 0},
        ]
    )
    sector_map = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000002.SZ", "sector_name": "算力"},
            {"ts_code": "000003.SZ", "sector_name": "机器人"},
            {"ts_code": "000004.SZ", "sector_name": "半导体"},
            {"ts_code": "000005.SZ", "sector_name": "低空经济"},
        ]
    )

    result = build_sector_momentum_daily(limit_rows, sector_map, max_mainlines=3)

    assert result[result["is_mainline"]].sort_values("rank")["sector_name"].tolist() == ["算力", "机器人", "半导体"]
    assert result["sector_score"].between(0, 100).all()


def test_sector_momentum_keeps_unique_mainline_when_first_sector_dominates() -> None:
    """第一名显著领先时，应只保留唯一主线。"""
    limit_rows = pd.DataFrame(
        [
            {"trade_date": "20260706", "ts_code": "000001.SZ", "name": "A1", "limit_type": "U", "amount": 300.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000002.SZ", "name": "A2", "limit_type": "U", "amount": 260.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000003.SZ", "name": "A3", "limit_type": "U", "amount": 220.0, "pct_chg": 10.0, "open_times": 0},
            {"trade_date": "20260706", "ts_code": "000004.SZ", "name": "B1", "limit_type": "U", "amount": 20.0, "pct_chg": 10.0, "open_times": 2},
        ]
    )
    sector_map = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000002.SZ", "sector_name": "算力"},
            {"ts_code": "000003.SZ", "sector_name": "算力"},
            {"ts_code": "000004.SZ", "sector_name": "机器人"},
        ]
    )

    result = build_sector_momentum_daily(limit_rows, sector_map, max_mainlines=3)

    assert result[result["is_mainline"]]["sector_name"].tolist() == ["算力"]
