"""
测试市场宽度快照模块
"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backtest.market_breadth import MarketBreadthCache, fetch_eastmoney_a_spot, get_market_breadth


class TestMarketBreadth(unittest.TestCase):
    """测试涨停数、上涨数、下跌数等市场宽度指标"""

    def setUp(self):
        """每个测试使用独立缓存文件"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "market_breadth.sqlite3"
        self.cache = MarketBreadthCache(self.cache_path)

    def tearDown(self):
        """关闭缓存连接并清理临时文件"""
        self.cache.close()
        self.temp_dir.cleanup()

    def test_get_market_breadth_calculates_counts_from_remote_data(self):
        """应基于涨停池和全A快照计算市场宽度"""
        def fetch_limit_up(_date: str) -> pd.DataFrame:
            return pd.DataFrame({"代码": ["000001", "000002"]})

        def fetch_spot() -> pd.DataFrame:
            return pd.DataFrame({"涨跌幅": [1.2, -0.5, 0.0, 3.4, -2.1]})

        result = get_market_breadth(
            date_str="20260602",
            cache=self.cache,
            fetch_limit_up=fetch_limit_up,
            fetch_spot=fetch_spot,
            now=datetime(2026, 6, 2, 10, 30),
        )

        self.assertEqual(result["涨停数"], 2)
        self.assertEqual(result["上涨数"], 2)
        self.assertEqual(result["下跌数"], 2)
        self.assertEqual(result["平盘数"], 1)
        self.assertEqual(result["provider"], "eastmoney")

    def test_get_market_breadth_uses_cache_before_ttl_expires(self):
        """盘中缓存未过期时，应直接读取缓存，不再请求接口"""
        self.cache.save_snapshot(
            {
                "date": "20260602",
                "涨停数": 8,
                "上涨数": 3000,
                "下跌数": 1800,
                "平盘数": 100,
                "provider": "eastmoney",
            },
            fetched_at=datetime(2026, 6, 2, 10, 0),
        )

        def fail_limit_up(_date: str) -> pd.DataFrame:
            raise AssertionError("缓存未过期时不应请求涨停池")

        def fail_spot() -> pd.DataFrame:
            raise AssertionError("缓存未过期时不应请求全A快照")

        result = get_market_breadth(
            date_str="20260602",
            cache=self.cache,
            fetch_limit_up=fail_limit_up,
            fetch_spot=fail_spot,
            now=datetime(2026, 6, 2, 10, 5),
            ttl_minutes=15,
        )

        self.assertEqual(result["上涨数"], 3000)
        self.assertEqual(result["下跌数"], 1800)

    def test_get_market_breadth_refreshes_after_ttl_expires(self):
        """盘中缓存过期后，应重新请求并覆盖缓存"""
        self.cache.save_snapshot(
            {
                "date": "20260602",
                "涨停数": 1,
                "上涨数": 1,
                "下跌数": 1,
                "平盘数": 1,
                "provider": "eastmoney",
            },
            fetched_at=datetime(2026, 6, 2, 9, 30),
        )

        result = get_market_breadth(
            date_str="20260602",
            cache=self.cache,
            fetch_limit_up=lambda _date: pd.DataFrame({"代码": ["000001", "000002", "000003"]}),
            fetch_spot=lambda: pd.DataFrame({"涨跌幅": [2.0, 0.0, -1.0]}),
            now=datetime(2026, 6, 2, 10, 0),
            ttl_minutes=15,
        )

        self.assertEqual(result["涨停数"], 3)
        self.assertEqual(result["上涨数"], 1)
        self.assertEqual(result["下跌数"], 1)
        self.assertEqual(result["平盘数"], 1)

    def test_after_market_close_cache_is_reused_permanently(self):
        """收盘后缓存视为稳定快照，应长期复用"""
        self.cache.save_snapshot(
            {
                "date": "20260602",
                "涨停数": 10,
                "上涨数": 3500,
                "下跌数": 1200,
                "平盘数": 80,
                "provider": "eastmoney",
            },
            fetched_at=datetime(2026, 6, 2, 15, 30),
        )

        result = get_market_breadth(
            date_str="20260602",
            cache=self.cache,
            fetch_limit_up=lambda _date: (_ for _ in ()).throw(AssertionError("不应刷新")),
            fetch_spot=lambda: (_ for _ in ()).throw(AssertionError("不应刷新")),
            now=datetime(2026, 6, 3, 10, 0),
        )

        self.assertEqual(result["涨停数"], 10)
        self.assertEqual(result["上涨数"], 3500)

    def test_fetch_eastmoney_a_spot_reads_all_pages(self):
        """东方财富全A快照应分页拉取，避免只统计前100只股票"""
        class FakeResponse:
            """模拟 requests 返回对象"""

            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

        payloads = [
            {"data": {"total": 5, "diff": [{"f12": "1", "f14": "A", "f3": 1.0}, {"f12": "2", "f14": "B", "f3": -1.0}]}},
            {"data": {"total": 5, "diff": [{"f12": "3", "f14": "C", "f3": 0.0}, {"f12": "4", "f14": "D", "f3": 2.0}]}},
            {"data": {"total": 5, "diff": [{"f12": "5", "f14": "E", "f3": -2.0}]}},
        ]

        with patch("backtest.market_breadth.requests.get", side_effect=[FakeResponse(payload) for payload in payloads]) as mock_get:
            result = fetch_eastmoney_a_spot(page_size=2)

        self.assertEqual(len(result), 5)
        self.assertEqual(mock_get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
