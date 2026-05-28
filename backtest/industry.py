"""
行业分类模块 (Industry Classification Module)
基于申万行业分类提供A股行业树与代表股票查询能力
"""

from copy import deepcopy
from typing import Dict, List, Optional


SW_INDUSTRY_TREE: Dict[str, Dict[str, Dict[str, List[Dict[str, str]]]]] = {
    "农林牧渔": {
        "种植业": {
            "粮食种植": [
                {"code": "600598.SH", "name": "北大荒"},
                {"code": "600108.SH", "name": "亚盛集团"},
                {"code": "600313.SH", "name": "农发种业"},
            ]
        }
    },
    "基础化工": {
        "化学制品": {
            "氟化工": [
                {"code": "600160.SH", "name": "巨化股份"},
                {"code": "002407.SZ", "name": "多氟多"},
                {"code": "600378.SH", "name": "昊华科技"},
            ]
        }
    },
    "钢铁": {
        "普钢": {
            "板材": [
                {"code": "600019.SH", "name": "宝钢股份"},
                {"code": "600010.SH", "name": "包钢股份"},
                {"code": "000709.SZ", "name": "河钢股份"},
            ]
        }
    },
    "有色金属": {
        "工业金属": {
            "铜铝加工": [
                {"code": "600362.SH", "name": "江西铜业"},
                {"code": "601600.SH", "name": "中国铝业"},
                {"code": "000878.SZ", "name": "云南铜业"},
            ]
        }
    },
    "电子": {
        "半导体": {
            "芯片设计": [
                {"code": "603986.SH", "name": "兆易创新"},
                {"code": "688008.SH", "name": "澜起科技"},
                {"code": "688981.SH", "name": "中芯国际"},
            ]
        }
    },
    "汽车": {
        "乘用车": {
            "整车制造": [
                {"code": "002594.SZ", "name": "比亚迪"},
                {"code": "601633.SH", "name": "长城汽车"},
                {"code": "600104.SH", "name": "上汽集团"},
            ]
        }
    },
    "家用电器": {
        "白色家电": {
            "空调冰洗": [
                {"code": "000651.SZ", "name": "格力电器"},
                {"code": "000333.SZ", "name": "美的集团"},
                {"code": "600690.SH", "name": "海尔智家"},
            ]
        }
    },
    "食品饮料": {
        "白酒": {
            "高端白酒": [
                {"code": "600519.SH", "name": "贵州茅台"},
                {"code": "000858.SZ", "name": "五粮液"},
                {"code": "000568.SZ", "name": "泸州老窖"},
            ]
        }
    },
    "纺织服装": {
        "服装家纺": {
            "品牌服饰": [
                {"code": "002832.SZ", "name": "比音勒芬"},
                {"code": "603877.SH", "name": "太平鸟"},
                {"code": "600398.SH", "name": "海澜之家"},
            ]
        }
    },
    "医药生物": {
        "化学制药": {
            "创新药": [
                {"code": "600276.SH", "name": "恒瑞医药"},
                {"code": "300759.SZ", "name": "康龙化成"},
                {"code": "688180.SH", "name": "君实生物"},
            ]
        }
    },
    "公用事业": {
        "电力": {
            "火电水电运营": [
                {"code": "600900.SH", "name": "长江电力"},
                {"code": "600011.SH", "name": "华能国际"},
                {"code": "600027.SH", "name": "华电国际"},
            ]
        }
    },
    "交通运输": {
        "物流": {
            "综合物流": [
                {"code": "002120.SZ", "name": "韵达股份"},
                {"code": "002352.SZ", "name": "顺丰控股"},
                {"code": "600233.SH", "name": "圆通速递"},
            ]
        }
    },
    "房地产": {
        "房地产开发": {
            "住宅开发": [
                {"code": "000002.SZ", "name": "万科A"},
                {"code": "600048.SH", "name": "保利发展"},
                {"code": "001979.SZ", "name": "招商蛇口"},
            ]
        }
    },
    "商贸零售": {
        "一般零售": {
            "连锁商超": [
                {"code": "601933.SH", "name": "永辉超市"},
                {"code": "600827.SH", "name": "百联股份"},
                {"code": "002419.SZ", "name": "天虹股份"},
            ]
        }
    },
    "银行": {
        "股份制银行": {
            "全国性商业银行": [
                {"code": "000001.SZ", "name": "平安银行"},
                {"code": "600036.SH", "name": "招商银行"},
                {"code": "601998.SH", "name": "中信银行"},
            ]
        }
    },
    "非银金融": {
        "证券": {
            "综合券商": [
                {"code": "600030.SH", "name": "中信证券"},
                {"code": "601211.SH", "name": "国泰海通"},
                {"code": "601688.SH", "name": "华泰证券"},
            ]
        }
    },
    "计算机": {
        "软件开发": {
            "基础软件": [
                {"code": "600588.SH", "name": "用友网络"},
                {"code": "600570.SH", "name": "恒生电子"},
                {"code": "300033.SZ", "name": "同花顺"},
            ]
        }
    },
    "传媒": {
        "数字媒体": {
            "互联网内容": [
                {"code": "002555.SZ", "name": "三七互娱"},
                {"code": "300413.SZ", "name": "芒果超媒"},
                {"code": "002027.SZ", "name": "分众传媒"},
            ]
        }
    },
    "通信": {
        "通信设备": {
            "光模块": [
                {"code": "300308.SZ", "name": "中际旭创"},
                {"code": "300502.SZ", "name": "新易盛"},
                {"code": "600498.SH", "name": "烽火通信"},
            ]
        }
    },
    "煤炭": {
        "煤炭开采": {
            "动力煤": [
                {"code": "601088.SH", "name": "中国神华"},
                {"code": "601225.SH", "name": "陕西煤业"},
                {"code": "600188.SH", "name": "兖矿能源"},
            ]
        }
    },
    "石油石化": {
        "炼化及贸易": {
            "炼油化工": [
                {"code": "600028.SH", "name": "中国石化"},
                {"code": "601857.SH", "name": "中国石油"},
                {"code": "600346.SH", "name": "恒力石化"},
            ]
        }
    },
    "电力设备": {
        "电池": {
            "锂电池": [
                {"code": "300750.SZ", "name": "宁德时代"},
                {"code": "002460.SZ", "name": "赣锋锂业"},
                {"code": "300014.SZ", "name": "亿纬锂能"},
            ]
        }
    },
    "国防军工": {
        "航空装备": {
            "军机产业链": [
                {"code": "000768.SZ", "name": "中航西飞"},
                {"code": "600760.SH", "name": "中航沈飞"},
                {"code": "002179.SZ", "name": "中航光电"},
            ]
        }
    },
    "机械设备": {
        "通用设备": {
            "工业自动化": [
                {"code": "300124.SZ", "name": "汇川技术"},
                {"code": "688017.SH", "name": "绿的谐波"},
                {"code": "300450.SZ", "name": "先导智能"},
            ]
        }
    },
    "建筑材料": {
        "水泥": {
            "区域水泥": [
                {"code": "600585.SH", "name": "海螺水泥"},
                {"code": "000877.SZ", "name": "天山股份"},
                {"code": "600801.SH", "name": "华新水泥"},
            ]
        }
    },
    "建筑装饰": {
        "基础建设": {
            "基建工程": [
                {"code": "601668.SH", "name": "中国建筑"},
                {"code": "601390.SH", "name": "中国中铁"},
                {"code": "601800.SH", "name": "中国交建"},
            ]
        }
    },
    "轻工制造": {
        "造纸": {
            "包装纸": [
                {"code": "002078.SZ", "name": "太阳纸业"},
                {"code": "600567.SH", "name": "山鹰国际"},
                {"code": "600966.SH", "name": "博汇纸业"},
            ]
        }
    },
    "社会服务": {
        "酒店餐饮": {
            "连锁餐饮": [
                {"code": "605108.SH", "name": "同庆楼"},
                {"code": "603043.SH", "name": "广州酒家"},
                {"code": "600258.SH", "name": "首旅酒店"},
            ]
        }
    },
    "综合": {
        "综合类": {
            "多元化经营": [
                {"code": "600770.SH", "name": "综艺股份"},
                {"code": "000009.SZ", "name": "中国宝安"},
                {"code": "600620.SH", "name": "天宸股份"},
            ]
        }
    },
    "环保": {
        "环境治理": {
            "固废处理": [
                {"code": "000826.SZ", "name": "启迪环境"},
                {"code": "300070.SZ", "name": "碧水源"},
                {"code": "601200.SH", "name": "上海环境"},
            ]
        }
    },
    "美容护理": {
        "个护用品": {
            "美妆护理": [
                {"code": "603605.SH", "name": "珀莱雅"},
                {"code": "300957.SZ", "name": "贝泰妮"},
                {"code": "603983.SH", "name": "丸美生物"},
            ]
        }
    },
}


class IndustryManager:
    """A股行业分类管理器 (A-share Industry Manager)"""

    def __init__(
        self,
        industry_tree: Optional[Dict[str, Dict[str, Dict[str, List[Dict[str, str]]]]]] = None,
    ):
        self._industry_tree = industry_tree or SW_INDUSTRY_TREE
        self._stock_index = self._build_stock_index()

    def _build_stock_index(self) -> Dict[str, Dict[str, str]]:
        """构建股票到行业路径的索引"""
        stock_index: Dict[str, Dict[str, str]] = {}
        for level1, level2_map in self._industry_tree.items():
            for level2, level3_map in level2_map.items():
                for level3, stocks in level3_map.items():
                    for stock in stocks:
                        code = stock["code"]
                        if code not in stock_index:
                            stock_index[code] = {
                                "code": code,
                                "name": stock["name"],
                                "level1": level1,
                                "level2": level2,
                                "level3": level3,
                            }
        return stock_index

    def get_level1_industries(self) -> List[str]:
        """获取所有一级行业名称列表"""
        return list(self._industry_tree.keys())

    def get_level2_industries(self, level1: str) -> List[str]:
        """根据一级行业获取二级行业列表"""
        return list(self._industry_tree.get(level1, {}).keys())

    def get_level3_industries(self, level1: str, level2: str) -> List[str]:
        """根据一级和二级行业获取三级行业列表"""
        return list(self._industry_tree.get(level1, {}).get(level2, {}).keys())

    def _format_stocks(self, level1: str, level2: str, level3: str) -> List[Dict[str, str]]:
        """格式化指定三级行业下股票列表（私有方法，调用方已完成路径校验）"""
        stocks = self._industry_tree[level1][level2][level3]
        return [
            {
                "code": stock["code"],
                "name": stock["name"],
                "level1": level1,
                "level2": level2,
                "level3": level3,
            }
            for stock in stocks
        ]

    def get_stocks(
        self, level1: str, level2: Optional[str] = None, level3: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        获取指定行业的股票列表
        - 只传 level1: 返回该一级行业下所有股票
        - 传 level1+level2: 返回该二级行业下所有股票
        - 传 level1+level2+level3: 返回该三级行业下的股票
        """
        if level1 not in self._industry_tree:
            return []

        if level2 is None:
            stocks: List[Dict[str, str]] = []
            for l2, l3_map in self._industry_tree[level1].items():
                for l3 in l3_map:
                    stocks.extend(self._format_stocks(level1, l2, l3))
            return stocks

        if level2 not in self._industry_tree[level1]:
            return []

        if level3 is None:
            stocks = []
            for l3 in self._industry_tree[level1][level2]:
                stocks.extend(self._format_stocks(level1, level2, l3))
            return stocks

        if level3 not in self._industry_tree[level1][level2]:
            return []

        return self._format_stocks(level1, level2, level3)

    def get_industry_by_stock(self, code: str) -> Dict[str, str]:
        """根据股票代码查询所属行业（返回一/二/三级行业信息）"""
        return deepcopy(self._stock_index.get(code, {}))

    def search_industry(self, keyword: str) -> List[Dict[str, str]]:
        """按关键字搜索行业名称，返回匹配的行业路径列表"""
        if not keyword:
            return []

        results: List[Dict[str, str]] = []
        lowered = keyword.lower()
        for level1, level2_map in self._industry_tree.items():
            if lowered in level1.lower():
                results.append({"level1": level1, "path": level1})

            for level2, level3_map in level2_map.items():
                if lowered in level2.lower():
                    results.append(
                        {"level1": level1, "level2": level2, "path": f"{level1} > {level2}"}
                    )

                for level3 in level3_map.keys():
                    if lowered in level3.lower():
                        results.append(
                            {
                                "level1": level1,
                                "level2": level2,
                                "level3": level3,
                                "path": f"{level1} > {level2} > {level3}",
                            }
                        )
        return results

    def get_industry_tree(self, level1: Optional[str] = None) -> Dict[str, Dict]:
        """获取行业树状结构，不传参数时返回完整树"""
        if level1 is None:
            return deepcopy(self._industry_tree)
        if level1 not in self._industry_tree:
            return {}
        return {level1: deepcopy(self._industry_tree[level1])}
