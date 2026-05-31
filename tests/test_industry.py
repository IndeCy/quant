"""
测试行业分类模块
"""

import unittest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.industry import IndustryManager

EXPECTED_LEVEL1_COUNT = 31
MIN_STOCKS_PER_LEVEL3 = 3
EXPECTED_BANK_STOCK_COUNT = 3


class TestIndustryManager(unittest.TestCase):
    """测试IndustryManager类"""

    def setUp(self):
        self.manager = IndustryManager()

    def test_get_level1_industries(self):
        """测试获取一级行业"""
        level1 = self.manager.get_level1_industries()
        self.assertIn("银行", level1)
        self.assertIn("电力设备", level1)
        self.assertEqual(len(level1), EXPECTED_LEVEL1_COUNT)

    def test_get_level2_and_level3_industries(self):
        """测试获取二级和三级行业"""
        level2 = self.manager.get_level2_industries("银行")
        self.assertIn("股份制银行", level2)
        self.assertGreaterEqual(len(level2), 1)

        level3 = self.manager.get_level3_industries("银行", "股份制银行")
        self.assertIn("全国性商业银行", level3)
        self.assertGreaterEqual(len(level3), 1)

    def test_get_stocks_by_levels(self):
        """测试按层级获取股票"""
        level1_stocks = self.manager.get_stocks("银行")
        self.assertGreaterEqual(len(level1_stocks), MIN_STOCKS_PER_LEVEL3)

        level2_stocks = self.manager.get_stocks("银行", "股份制银行")
        level1_codes = {item["code"] for item in level1_stocks}
        level2_codes = {item["code"] for item in level2_stocks}
        self.assertTrue(level2_codes.issubset(level1_codes))

        level3_stocks = self.manager.get_stocks("银行", "股份制银行", "全国性商业银行")
        self.assertEqual(len(level3_stocks), EXPECTED_BANK_STOCK_COUNT)
        level3_codes = {item["code"] for item in level3_stocks}
        self.assertTrue(level3_codes.issubset(level2_codes))
        self.assertEqual(level3_stocks[0]["level1"], "银行")
        self.assertEqual(level3_stocks[0]["level2"], "股份制银行")
        self.assertEqual(level3_stocks[0]["level3"], "全国性商业银行")

    def test_get_industry_by_stock(self):
        """测试按股票代码查询行业"""
        info = self.manager.get_industry_by_stock("000001.SZ")
        self.assertEqual(info["name"], "平安银行")
        self.assertEqual(info["level1"], "银行")
        self.assertEqual(info["level2"], "股份制银行")
        self.assertEqual(info["level3"], "全国性商业银行")

        self.assertEqual(self.manager.get_industry_by_stock("999999.SZ"), {})

    def test_search_industry(self):
        """测试关键字搜索行业"""
        results = self.manager.search_industry("银行")
        self.assertTrue(any(item["path"] == "银行" for item in results))
        self.assertTrue(any("股份制银行" in item["path"] for item in results))

        self.assertEqual(self.manager.search_industry(""), [])

    def test_get_industry_tree(self):
        """测试行业树查询"""
        full_tree = self.manager.get_industry_tree()
        self.assertIn("银行", full_tree)

        partial_tree = self.manager.get_industry_tree("银行")
        self.assertEqual(list(partial_tree.keys()), ["银行"])
        self.assertEqual(self.manager.get_industry_tree("不存在行业"), {})


if __name__ == "__main__":
    unittest.main()
