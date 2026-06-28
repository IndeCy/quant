"""Tushare 行业缓存测试。"""

from pathlib import Path

import pandas as pd

from backtest.industry import IndustryManager
from data.tushare_industry_incremental import IndustryDuckDBStore


def test_industry_store_upserts_rows(tmp_path: Path) -> None:
    """行业缓存应能写入并读取股票基础行业字段。"""
    store = IndustryDuckDBStore(tmp_path / "industry.duckdb")
    frame = pd.DataFrame(
        [
            {
                "ts_code": "999001.SZ",
                "symbol": "999001",
                "name": "测试银行",
                "area": "深圳",
                "industry": "银行",
                "market": "主板",
                "list_date": "20200101",
                "list_status": "L",
            }
        ]
    )

    result = store.upsert(frame)
    loaded = store.load()

    assert result.row_count == 1
    assert loaded.iloc[0]["industry"] == "银行"


def test_industry_manager_loads_tushare_cache(tmp_path: Path) -> None:
    """IndustryManager 应用 Tushare 缓存补齐内置树外股票。"""
    store = IndustryDuckDBStore(tmp_path / "industry.duckdb")
    store.upsert(
        pd.DataFrame(
            [
                {
                    "ts_code": "999888.SZ",
                    "symbol": "999888",
                    "name": "测试水泥",
                    "area": "北京",
                    "industry": "水泥",
                    "market": "主板",
                    "list_date": "20200101",
                    "list_status": "L",
                }
            ]
        )
    )

    manager = IndustryManager(industry_cache_path=tmp_path / "industry.duckdb")
    info = manager.get_industry_by_stock("999888.SZ")

    assert info["level1"] == "水泥"
    assert info["source"] == "tushare_stock_basic"
