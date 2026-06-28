"""
行业模块示例 (Industry Module Example)
演示如何使用行业分类管理器筛选A股股票池
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.industry import IndustryManager


def main():
    """主函数"""
    manager = IndustryManager()

    # 1. 列出所有一级行业
    print("一级行业列表:")
    level1_list = manager.get_level1_industries()
    print(level1_list)

    # 2. 查询某一级行业下的二/三级行业
    level1 = "电力设备"
    level2_list = manager.get_level2_industries(level1)
    print(f"\n{level1} 二级行业:", level2_list)

    level2 = level2_list[0]
    level3_list = manager.get_level3_industries(level1, level2)
    print(f"{level1} > {level2} 三级行业:", level3_list)

    # 3. 获取某三级行业的股票列表
    level3 = level3_list[0]
    stocks = manager.get_stocks(level1, level2, level3)
    print(f"\n{level1} > {level2} > {level3} 股票:")
    for stock in stocks:
        print(f"- {stock['code']} {stock['name']}")

    # 4. 根据股票代码查询行业归属
    code = "300750.SZ"
    industry_info = manager.get_industry_by_stock(code)
    print(f"\n{code} 行业归属:", industry_info)

    # 5. 筛选某行业下全部股票用于回测
    bank_stocks = manager.get_stocks("银行")
    symbols = [item["code"] for item in bank_stocks]
    print("\n银行行业股票池（可用于回测）:", symbols)


if __name__ == "__main__":
    main()
