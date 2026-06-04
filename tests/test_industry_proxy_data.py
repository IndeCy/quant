"""
测试行业代理数据源
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backtest.cache import MarketDataCache
from backtest.industry_proxy import (
    INDUSTRY_PROXY_ETFS,
    fetch_industry_proxy_klines,
    get_default_industry_proxy_symbols,
    tencent_security_code,
)
from examples.shanghai_index_ma_backtest import ADJUST, FREQUENCY, TENCENT_PROVIDER


class TestIndustryProxyData(unittest.TestCase):
    """测试行业 ETF 代理数据源"""

    def test_default_proxy_pool_contains_core_themes(self):
        """默认代理池应覆盖当前关注的核心行业方向"""
        self.assertIn("电力", INDUSTRY_PROXY_ETFS)
        self.assertIn("半导体", INDUSTRY_PROXY_ETFS)
        self.assertIn("通信设备", INDUSTRY_PROXY_ETFS)
        self.assertIn("设备制造", INDUSTRY_PROXY_ETFS)
        self.assertIn("汽车", INDUSTRY_PROXY_ETFS)
        self.assertIn("煤炭", INDUSTRY_PROXY_ETFS)
        self.assertIn("银行", INDUSTRY_PROXY_ETFS)
        self.assertIn("红利低波", INDUSTRY_PROXY_ETFS)
        self.assertIn("黄金", INDUSTRY_PROXY_ETFS)
        self.assertIn("医药", INDUSTRY_PROXY_ETFS)
        self.assertIn("运营商", INDUSTRY_PROXY_ETFS)

    def test_get_default_industry_proxy_symbols_returns_codes(self):
        """默认代理池应返回行业名称到证券代码的映射"""
        symbols = get_default_industry_proxy_symbols()

        self.assertEqual(symbols["半导体"], INDUSTRY_PROXY_ETFS["半导体"].symbol)
        self.assertEqual(symbols["半导体"], "159995.SZ")
        self.assertEqual(symbols["通信设备"], "159695.SZ")
        self.assertEqual(symbols["有色金属"], "159980.SZ")
        self.assertEqual(symbols["煤炭"], "159930.SZ")
        self.assertEqual(symbols["银行"], "159887.SZ")
        self.assertEqual(symbols["红利低波"], "159549.SZ")
        self.assertEqual(symbols["黄金"], "517520.SH")
        self.assertEqual(symbols["医药"], "159929.SZ")
        self.assertEqual(symbols["运营商"], "560680.SH")

    def test_tencent_security_code_supports_sh_and_sz_symbols(self):
        """腾讯证券代码转换应支持沪深 ETF"""
        self.assertEqual(tencent_security_code("512480.SH"), "sh512480")
        self.assertEqual(tencent_security_code("159995.SZ"), "sz159995")

    def test_fetch_industry_proxy_klines_reads_covered_cache(self):
        """行业代理行情已被缓存覆盖时，不应再次请求外部接口"""
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "market_cache.sqlite3"
            cache = MarketDataCache(cache_path)
            cached_df = pd.DataFrame(
                {
                    "open": [1.0, 1.1],
                    "high": [1.2, 1.3],
                    "low": [0.9, 1.0],
                    "close": [1.1, 1.2],
                    "volume": [1000.0, 1200.0],
                    "amount": [0.0, 0.0],
                },
                index=pd.date_range("2026-05-01", periods=2, freq="D"),
            )
            cache.upsert_bars(TENCENT_PROVIDER, "512480.SH", FREQUENCY, ADJUST, cached_df)
            cache.record_coverage(
                TENCENT_PROVIDER,
                "512480.SH",
                FREQUENCY,
                ADJUST,
                date(2026, 5, 1),
                date(2026, 5, 2),
            )
            cache.close()

            with patch(
                "backtest.industry_proxy._fetch_tencent_security_klines_remote",
                side_effect=AssertionError("缓存覆盖时不应请求外部接口"),
            ):
                actual = fetch_industry_proxy_klines(
                    "512480.SH",
                    date(2026, 5, 1),
                    date(2026, 5, 2),
                    cache_path=cache_path,
                )

        self.assertEqual(len(actual), 2)
        self.assertAlmostEqual(actual.iloc[-1]["close"], 1.2)


if __name__ == "__main__":
    unittest.main()
