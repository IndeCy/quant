"""
测试行业分类模块
"""

import json
import os
import sys
import tempfile
import unittest

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

    def test_litong_electronics_in_static_data(self):
        """测试利通电子已加入静态数据"""
        info = self.manager.get_industry_by_stock("002339.SZ")
        self.assertEqual(info["name"], "利通电子")
        self.assertEqual(info["level1"], "电子")
        self.assertEqual(info["level2"], "消费电子")
        self.assertEqual(info["level3"], "消费电子零部件")

    def test_add_stock(self):
        """测试单只股票动态添加"""
        manager = IndustryManager()
        manager.add_stock("999001.SZ", "测试股票", "测试行业", "测试二级", "测试三级")

        info = manager.get_industry_by_stock("999001.SZ")
        self.assertEqual(info["name"], "测试股票")
        self.assertEqual(info["level1"], "测试行业")
        self.assertIn("测试行业", manager.get_level1_industries())
        stocks = manager.get_stocks("测试行业", "测试二级", "测试三级")
        self.assertEqual(len(stocks), 1)
        self.assertEqual(stocks[0]["code"], "999001.SZ")

    def test_add_stock_duplicate_skipped(self):
        """测试重复添加同一股票代码时跳过"""
        manager = IndustryManager()
        manager.add_stock("999002.SZ", "重复股票", "行业A", "二级A", "三级A")
        manager.add_stock("999002.SZ", "重复股票改名", "行业B", "二级B", "三级B")

        info = manager.get_industry_by_stock("999002.SZ")
        self.assertEqual(info["name"], "重复股票")
        self.assertEqual(info["level1"], "行业A")

    def test_import_from_records(self):
        """测试从字典列表批量导入"""
        manager = IndustryManager()
        records = [
            {"code": "888001.SZ", "name": "批量A", "level1": "新行业", "level2": "新二级", "level3": "新三级"},
            {"code": "888002.SZ", "name": "批量B", "level1": "新行业", "level2": "新二级", "level3": "新三级"},
            {"code": "888001.SZ", "name": "批量A重复", "level1": "新行业", "level2": "新二级", "level3": "新三级"},
        ]
        added = manager.import_from_records(records)
        self.assertEqual(added, 2)
        self.assertEqual(manager.get_industry_by_stock("888001.SZ")["name"], "批量A")
        self.assertEqual(manager.get_industry_by_stock("888002.SZ")["name"], "批量B")

    def test_import_from_csv(self):
        """测试从 CSV 文件批量导入"""
        csv_content = (
            "code,name,level1,level2,level3\n"
            "777001.SZ,CSV股票A,CSV行业,CSV二级,CSV三级\n"
            "777002.SH,CSV股票B,CSV行业,CSV二级,CSV三级\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            manager = IndustryManager()
            added = manager.import_from_csv(csv_path)
            self.assertEqual(added, 2)
            self.assertEqual(manager.get_industry_by_stock("777001.SZ")["name"], "CSV股票A")
            self.assertEqual(manager.get_industry_by_stock("777002.SH")["level1"], "CSV行业")
        finally:
            os.unlink(csv_path)

    def test_import_from_json(self):
        """测试从 JSON 文件批量导入"""
        records = [
            {"code": "666001.SZ", "name": "JSON股票A", "level1": "JSON行业", "level2": "JSON二级", "level3": "JSON三级"},
            {"code": "666002.SH", "name": "JSON股票B", "level1": "JSON行业", "level2": "JSON二级", "level3": "JSON三级"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(records, f, ensure_ascii=False)
            json_path = f.name

        try:
            manager = IndustryManager()
            added = manager.import_from_json(json_path)
            self.assertEqual(added, 2)
            self.assertEqual(manager.get_industry_by_stock("666001.SZ")["name"], "JSON股票A")
            self.assertEqual(manager.get_industry_by_stock("666002.SH")["level2"], "JSON二级")
        finally:
            os.unlink(json_path)


if __name__ == "__main__":
    unittest.main()
