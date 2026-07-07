"""游资主线龙头研究视图测试。"""

from pathlib import Path

import duckdb
import pandas as pd

from runtime.hot_money_research_view import build_hot_money_research_view


def test_build_hot_money_research_view_returns_latest_mainlines(tmp_path: Path) -> None:
    """研究视图应从本地涨跌停缓存返回最新主线和龙头。"""
    db_path = tmp_path / "limit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE limit_list_daily AS
            SELECT * FROM (
                VALUES
                ('20260706','000001.SZ','A1',10.0,10.0,'U',120.0,0.0,'09:30','09:30',0),
                ('20260706','000002.SZ','A2',10.0,10.0,'U',60.0,0.0,'09:31','09:31',1)
            ) AS t(trade_date, ts_code, name, close, pct_chg, limit_type, amount, fd_amount, first_time, last_time, open_times)
            """
        )
    sector_map = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "sector_name": "算力"},
            {"ts_code": "000002.SZ", "sector_name": "算力"},
        ]
    )

    view = build_hot_money_research_view(db_path, sector_map)

    assert view["status"] == "READY"
    assert view["latest_trade_date"] == "20260706"
    assert view["mainlines"][0]["sector_name"] == "算力"
    assert view["leaders"][0]["role"] == "LEADER"


def test_build_hot_money_research_view_reports_missing_cache(tmp_path: Path) -> None:
    """缓存缺失时应返回可展示状态，而不是让前端报错。"""
    view = build_hot_money_research_view(tmp_path / "missing.duckdb")

    assert view["status"] == "MISSING_CACHE"
    assert view["mainlines"] == []
    assert view["leaders"] == []
