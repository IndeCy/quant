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
            ],
            "其他种植": [
                {"code": "000998.SZ", "name": "隆平高科"},
                {"code": "601952.SH", "name": "苏垦农发"},
                {"code": "300189.SZ", "name": "神农科技"},
            ],
        },
        "畜牧业": {
            "猪养殖": [
                {"code": "002714.SZ", "name": "牧原股份"},
                {"code": "300498.SZ", "name": "温氏股份"},
                {"code": "002157.SZ", "name": "正邦科技"},
            ],
            "禽养殖": [
                {"code": "002299.SZ", "name": "圣农发展"},
                {"code": "002458.SZ", "name": "益生股份"},
                {"code": "002746.SZ", "name": "仙坛股份"},
            ],
        },
        "渔业": {
            "渔业养殖": [
                {"code": "300094.SZ", "name": "国联水产"},
                {"code": "002069.SZ", "name": "獐子岛"},
                {"code": "600257.SH", "name": "大湖股份"},
            ],
        },
        "农业综合": {
            "农业综合": [
                {"code": "600737.SH", "name": "中粮糖业"},
                {"code": "000505.SZ", "name": "京粮控股"},
                {"code": "601000.SH", "name": "唐山港"},
            ],
        },
    },
    "基础化工": {
        "化学原料": {
            "纯碱氯碱": [
                {"code": "000822.SZ", "name": "山东海化"},
                {"code": "600409.SH", "name": "三友化工"},
                {"code": "002386.SZ", "name": "天原股份"},
            ],
        },
        "化学制品": {
            "氟化工": [
                {"code": "600160.SH", "name": "巨化股份"},
                {"code": "002407.SZ", "name": "多氟多"},
                {"code": "600378.SH", "name": "昊华科技"},
            ],
            "农药化肥": [
                {"code": "600486.SH", "name": "扬农化工"},
                {"code": "002258.SZ", "name": "利尔化学"},
                {"code": "002763.SZ", "name": "汉邦科技"},
            ],
            "钛白粉": [
                {"code": "002601.SZ", "name": "龙佰集团"},
                {"code": "002145.SZ", "name": "中核钛白"},
                {"code": "002136.SZ", "name": "安纳达"},
            ],
        },
        "化工新材料": {
            "高分子新材料": [
                {"code": "600309.SH", "name": "万华化学"},
                {"code": "002064.SZ", "name": "华峰化学"},
                {"code": "002408.SZ", "name": "齐翔腾达"},
            ],
            "碳纤维": [
                {"code": "300686.SZ", "name": "东方盛虹"},
                {"code": "688295.SH", "name": "中复神鹰"},
                {"code": "300693.SZ", "name": "盛剑环境"},
            ],
        },
        "化学纤维": {
            "粘胶纤维": [
                {"code": "002092.SZ", "name": "中泰化学"},
                {"code": "000902.SZ", "name": "新洋丰"},
                {"code": "600889.SH", "name": "南京化纤"},
            ],
        },
    },
    "钢铁": {
        "普钢": {
            "板材": [
                {"code": "600019.SH", "name": "宝钢股份"},
                {"code": "600010.SH", "name": "包钢股份"},
                {"code": "000709.SZ", "name": "河钢股份"},
            ],
            "长材": [
                {"code": "600507.SH", "name": "方大特钢"},
                {"code": "000932.SZ", "name": "华菱钢铁"},
                {"code": "601003.SH", "name": "柳钢股份"},
            ],
        },
        "特钢": {
            "特殊钢": [
                {"code": "600126.SH", "name": "杭钢股份"},
                {"code": "002110.SZ", "name": "三钢闽光"},
                {"code": "600231.SH", "name": "凌钢股份"},
            ],
        },
    },
    "有色金属": {
        "工业金属": {
            "铜铝加工": [
                {"code": "600362.SH", "name": "江西铜业"},
                {"code": "601600.SH", "name": "中国铝业"},
                {"code": "000878.SZ", "name": "云南铜业"},
            ],
            "锌铅镍": [
                {"code": "000612.SZ", "name": "焦作万方"},
                {"code": "601899.SH", "name": "紫金矿业"},
                {"code": "600489.SH", "name": "中金黄金"},
            ],
        },
        "小金属": {
            "钨钼稀土": [
                {"code": "002203.SZ", "name": "海亮股份"},
                {"code": "600547.SH", "name": "山东黄金"},
                {"code": "000831.SZ", "name": "中国稀土"},
            ],
            "钴镍锂": [
                {"code": "603799.SH", "name": "华友钴业"},
                {"code": "300818.SZ", "name": "耐普矿机"},
                {"code": "300618.SZ", "name": "寒锐钴业"},
            ],
        },
        "贵金属": {
            "黄金": [
                {"code": "600547.SH", "name": "山东黄金"},
                {"code": "601787.SH", "name": "中国黄金"},
                {"code": "000975.SZ", "name": "银泰黄金"},
            ],
        },
        "能源金属": {
            "锂资源": [
                {"code": "002460.SZ", "name": "赣锋锂业"},
                {"code": "002738.SZ", "name": "中矿资源"},
                {"code": "002554.SZ", "name": "惠博普"},
            ],
        },
    },
    "电子": {
        "半导体": {
            "芯片设计": [
                {"code": "603986.SH", "name": "兆易创新"},
                {"code": "688008.SH", "name": "澜起科技"},
                {"code": "688981.SH", "name": "中芯国际"},
            ],
            "晶圆代工封测": [
                {"code": "688012.SH", "name": "中微公司"},
                {"code": "688396.SH", "name": "华润微"},
                {"code": "002049.SZ", "name": "紫光国微"},
            ],
            "半导体材料设备": [
                {"code": "688126.SH", "name": "沪硅产业"},
                {"code": "688037.SH", "name": "芯源微"},
                {"code": "300604.SZ", "name": "长川科技"},
            ],
        },
        "消费电子": {
            "消费电子整机": [
                {"code": "002415.SZ", "name": "海康威视"},
                {"code": "002049.SZ", "name": "紫光国微"},
                {"code": "300866.SZ", "name": "安克创新"},
            ],
            "消费电子零部件": [
                {"code": "002841.SZ", "name": "视源股份"},
                {"code": "600183.SH", "name": "生益科技"},
                {"code": "002456.SZ", "name": "欧菲光"},
            ],
        },
        "光学光电子": {
            "光学元件": [
                {"code": "002916.SZ", "name": "深南电路"},
                {"code": "300454.SZ", "name": "深信服"},
                {"code": "688206.SH", "name": "概伦电子"},
            ],
        },
        "被动元件": {
            "电容电阻": [
                {"code": "600563.SH", "name": "法拉电子"},
                {"code": "300433.SZ", "name": "蓝思科技"},
                {"code": "002459.SZ", "name": "晶澳科技"},
            ],
        },
    },
    "汽车": {
        "乘用车": {
            "整车制造": [
                {"code": "002594.SZ", "name": "比亚迪"},
                {"code": "601633.SH", "name": "长城汽车"},
                {"code": "600104.SH", "name": "上汽集团"},
            ],
            "新能源整车": [
                {"code": "601238.SH", "name": "广汽集团"},
                {"code": "000625.SZ", "name": "长安汽车"},
                {"code": "600418.SH", "name": "江淮汽车"},
            ],
        },
        "商用车": {
            "重卡客车": [
                {"code": "000951.SZ", "name": "中国重汽"},
                {"code": "600375.SH", "name": "汉马科技"},
                {"code": "600066.SH", "name": "宇通客车"},
            ],
        },
        "汽车零部件": {
            "动力总成": [
                {"code": "600699.SH", "name": "均胜电子"},
                {"code": "002008.SZ", "name": "大族激光"},
                {"code": "300403.SZ", "name": "汉宇集团"},
            ],
            "车身底盘": [
                {"code": "601799.SH", "name": "星宇股份"},
                {"code": "002091.SZ", "name": "江苏通达"},
                {"code": "603799.SH", "name": "华友钴业"},
            ],
            "智能驾驶": [
                {"code": "002985.SZ", "name": "北摩高科"},
                {"code": "688488.SH", "name": "华海清科"},
                {"code": "300773.SZ", "name": "拉卡拉"},
            ],
        },
    },
    "家用电器": {
        "白色家电": {
            "空调冰洗": [
                {"code": "000651.SZ", "name": "格力电器"},
                {"code": "000333.SZ", "name": "美的集团"},
                {"code": "600690.SH", "name": "海尔智家"},
            ],
        },
        "小家电": {
            "厨卫小家电": [
                {"code": "002508.SZ", "name": "老板电器"},
                {"code": "002242.SZ", "name": "九阳股份"},
                {"code": "600839.SH", "name": "四川长虹"},
            ],
        },
        "黑色家电": {
            "彩电": [
                {"code": "000525.SZ", "name": "红塔红土"},
                {"code": "600660.SH", "name": "福耀玻璃"},
                {"code": "002456.SZ", "name": "欧菲光"},
            ],
        },
        "厨卫电器": {
            "热水器油烟机": [
                {"code": "002050.SZ", "name": "三花智控"},
                {"code": "002337.SZ", "name": "赛象科技"},
                {"code": "600690.SH", "name": "海尔智家"},
            ],
        },
    },
    "食品饮料": {
        "白酒": {
            "高端白酒": [
                {"code": "600519.SH", "name": "贵州茅台"},
                {"code": "000858.SZ", "name": "五粮液"},
                {"code": "000568.SZ", "name": "泸州老窖"},
            ],
            "次高端白酒": [
                {"code": "000596.SZ", "name": "古井贡酒"},
                {"code": "600779.SH", "name": "水井坊"},
                {"code": "002304.SZ", "name": "洋河股份"},
            ],
            "区域白酒": [
                {"code": "603589.SH", "name": "口子窖"},
                {"code": "600415.SH", "name": "小商品城"},
                {"code": "000799.SZ", "name": "酒鬼酒"},
            ],
        },
        "啤酒": {
            "啤酒酿造": [
                {"code": "600694.SH", "name": "百联股份"},
                {"code": "000729.SZ", "name": "燕京啤酒"},
                {"code": "600132.SH", "name": "重庆啤酒"},
            ],
        },
        "饮料乳品": {
            "乳制品": [
                {"code": "600887.SH", "name": "伊利股份"},
                {"code": "002946.SZ", "name": "新乳业"},
                {"code": "600597.SH", "name": "光明乳业"},
            ],
            "饮料": [
                {"code": "605499.SH", "name": "东鹏饮料"},
                {"code": "002507.SZ", "name": "涪陵榨菜"},
                {"code": "603288.SH", "name": "海天味业"},
            ],
        },
        "食品加工": {
            "调味品": [
                {"code": "603288.SH", "name": "海天味业"},
                {"code": "600872.SH", "name": "中炬高新"},
                {"code": "002507.SZ", "name": "涪陵榨菜"},
            ],
            "休闲食品": [
                {"code": "002507.SZ", "name": "涪陵榨菜"},
                {"code": "603719.SH", "name": "良品铺子"},
                {"code": "002650.SZ", "name": "加加食品"},
            ],
        },
    },
    "纺织服装": {
        "服装家纺": {
            "品牌服饰": [
                {"code": "002832.SZ", "name": "比音勒芬"},
                {"code": "603877.SH", "name": "太平鸟"},
                {"code": "600398.SH", "name": "海澜之家"},
            ],
            "家纺": [
                {"code": "603365.SH", "name": "水星家纺"},
                {"code": "002397.SZ", "name": "梦洁股份"},
                {"code": "601718.SH", "name": "际华集团"},
            ],
        },
        "纺织制造": {
            "印染纺纱": [
                {"code": "601106.SH", "name": "中航重机"},
                {"code": "000652.SZ", "name": "泰达股份"},
                {"code": "600540.SH", "name": "新赛股份"},
            ],
        },
    },
    "医药生物": {
        "化学制药": {
            "创新药": [
                {"code": "600276.SH", "name": "恒瑞医药"},
                {"code": "300759.SZ", "name": "康龙化成"},
                {"code": "688180.SH", "name": "君实生物"},
            ],
            "仿制药": [
                {"code": "600812.SH", "name": "华北制药"},
                {"code": "600998.SH", "name": "九州通"},
                {"code": "000989.SZ", "name": "九芝堂"},
            ],
        },
        "生物制品": {
            "疫苗": [
                {"code": "300122.SZ", "name": "智飞生物"},
                {"code": "300601.SZ", "name": "康泰生物"},
                {"code": "300142.SZ", "name": "沃森生物"},
            ],
            "血液制品": [
                {"code": "000926.SZ", "name": "福星股份"},
                {"code": "002252.SZ", "name": "上海莱士"},
                {"code": "300198.SZ", "name": "纳尔股份"},
            ],
        },
        "中药": {
            "中药饮片": [
                {"code": "600085.SH", "name": "同仁堂"},
                {"code": "000538.SZ", "name": "云南白药"},
                {"code": "600436.SH", "name": "片仔癀"},
            ],
            "中成药": [
                {"code": "600739.SH", "name": "辽宁成大"},
                {"code": "000999.SZ", "name": "华润三九"},
                {"code": "600513.SH", "name": "联环药业"},
            ],
        },
        "医疗器械": {
            "体外诊断": [
                {"code": "300841.SZ", "name": "康华医疗"},
                {"code": "300314.SZ", "name": "戴维医疗"},
                {"code": "688050.SH", "name": "爱博医疗"},
            ],
            "医疗设备": [
                {"code": "300760.SZ", "name": "迈瑞医疗"},
                {"code": "688687.SH", "name": "凯因科技"},
                {"code": "603195.SH", "name": "公牛集团"},
            ],
        },
        "医疗服务": {
            "医院连锁": [
                {"code": "300015.SZ", "name": "爱尔眼科"},
                {"code": "600763.SH", "name": "通策医疗"},
                {"code": "002589.SZ", "name": "瑞康医药"},
            ],
        },
    },
    "公用事业": {
        "电力": {
            "火电水电运营": [
                {"code": "600900.SH", "name": "长江电力"},
                {"code": "600011.SH", "name": "华能国际"},
                {"code": "600027.SH", "name": "华电国际"},
            ],
            "新能源发电": [
                {"code": "601012.SH", "name": "隆基绿能"},
                {"code": "000591.SZ", "name": "太阳能"},
                {"code": "600905.SH", "name": "三峡能源"},
            ],
        },
        "燃气": {
            "天然气管网": [
                {"code": "601728.SH", "name": "中国电信"},
                {"code": "600803.SH", "name": "新奥股份"},
                {"code": "002911.SZ", "name": "佛燃能源"},
            ],
        },
        "水务": {
            "供水排水": [
                {"code": "600009.SH", "name": "上海机场"},
                {"code": "600684.SH", "name": "珠江股份"},
                {"code": "601199.SH", "name": "江南水务"},
            ],
        },
    },
    "交通运输": {
        "航空机场": {
            "航空公司": [
                {"code": "601111.SH", "name": "中国国航"},
                {"code": "600115.SH", "name": "中国东航"},
                {"code": "600029.SH", "name": "南方航空"},
            ],
            "机场": [
                {"code": "600009.SH", "name": "上海机场"},
                {"code": "000089.SZ", "name": "深圳机场"},
                {"code": "600004.SH", "name": "白云机场"},
            ],
        },
        "铁路公路": {
            "铁路运营": [
                {"code": "601816.SH", "name": "京沪高铁"},
                {"code": "000088.SZ", "name": "盐田港"},
                {"code": "600033.SH", "name": "福建高速"},
            ],
            "公路运营": [
                {"code": "600269.SH", "name": "赣粤高速"},
                {"code": "600012.SH", "name": "皖通高速"},
                {"code": "000429.SZ", "name": "粤高速A"},
            ],
        },
        "物流快递": {
            "综合物流": [
                {"code": "002120.SZ", "name": "韵达股份"},
                {"code": "002352.SZ", "name": "顺丰控股"},
                {"code": "600233.SH", "name": "圆通速递"},
            ],
        },
        "港口航运": {
            "港口": [
                {"code": "600018.SH", "name": "上港集团"},
                {"code": "000507.SZ", "name": "珠海港"},
                {"code": "600717.SH", "name": "天津港"},
            ],
        },
    },
    "房地产": {
        "房地产开发": {
            "住宅开发": [
                {"code": "000002.SZ", "name": "万科A"},
                {"code": "600048.SH", "name": "保利发展"},
                {"code": "001979.SZ", "name": "招商蛇口"},
            ],
            "商业地产": [
                {"code": "000656.SZ", "name": "金科股份"},
                {"code": "600340.SH", "name": "华夏幸福"},
                {"code": "600383.SH", "name": "金地集团"},
            ],
        },
        "房地产服务": {
            "物业管理": [
                {"code": "603722.SH", "name": "合众思壮"},
                {"code": "002244.SZ", "name": "滨江集团"},
                {"code": "600606.SH", "name": "绿地控股"},
            ],
        },
    },
    "商贸零售": {
        "一般零售": {
            "连锁商超": [
                {"code": "601933.SH", "name": "永辉超市"},
                {"code": "600827.SH", "name": "百联股份"},
                {"code": "002419.SZ", "name": "天虹股份"},
            ],
            "百货": [
                {"code": "600892.SH", "name": "大晟文化"},
                {"code": "600631.SH", "name": "第一百货"},
                {"code": "000157.SZ", "name": "中联重科"},
            ],
        },
        "专业零售": {
            "品牌连锁": [
                {"code": "002503.SZ", "name": "搜于特"},
                {"code": "002029.SZ", "name": "七匹狼"},
                {"code": "600352.SH", "name": "浙江龙盛"},
            ],
        },
        "贸易": {
            "大宗商品贸易": [
                {"code": "600120.SH", "name": "浙江东日"},
                {"code": "600265.SH", "name": "景谷林业"},
                {"code": "600758.SH", "name": "红阳能源"},
            ],
        },
    },
    "银行": {
        "国有行": {
            "六大国有行": [
                {"code": "601398.SH", "name": "工商银行"},
                {"code": "601939.SH", "name": "建设银行"},
                {"code": "601288.SH", "name": "农业银行"},
            ],
        },
        "股份制银行": {
            "全国性商业银行": [
                {"code": "000001.SZ", "name": "平安银行"},
                {"code": "600036.SH", "name": "招商银行"},
                {"code": "601998.SH", "name": "中信银行"},
            ],
        },
        "城商行": {
            "城市商业银行": [
                {"code": "601166.SH", "name": "兴业银行"},
                {"code": "600016.SH", "name": "民生银行"},
                {"code": "601009.SH", "name": "南京银行"},
            ],
        },
        "农商行": {
            "农村商业银行": [
                {"code": "601128.SH", "name": "常熟银行"},
                {"code": "002936.SZ", "name": "郑州银行"},
                {"code": "601077.SH", "name": "渝农商行"},
            ],
        },
    },
    "非银金融": {
        "证券": {
            "综合券商": [
                {"code": "600030.SH", "name": "中信证券"},
                {"code": "601211.SH", "name": "国泰海通"},
                {"code": "601688.SH", "name": "华泰证券"},
            ],
            "互联网券商": [
                {"code": "601375.SH", "name": "中原证券"},
                {"code": "000750.SZ", "name": "国海证券"},
                {"code": "601198.SH", "name": "东兴证券"},
            ],
        },
        "保险": {
            "寿险": [
                {"code": "601628.SH", "name": "中国人寿"},
                {"code": "601318.SH", "name": "中国平安"},
                {"code": "601601.SH", "name": "中国太保"},
            ],
            "财险": [
                {"code": "601319.SH", "name": "中国人保"},
                {"code": "601336.SH", "name": "新华保险"},
                {"code": "600621.SH", "name": "华鑫股份"},
            ],
        },
        "多元金融": {
            "信托租赁": [
                {"code": "600816.SH", "name": "安信信托"},
                {"code": "000563.SZ", "name": "陕国投A"},
                {"code": "600643.SH", "name": "爱建集团"},
            ],
        },
    },
    "计算机": {
        "软件开发": {
            "基础软件": [
                {"code": "600588.SH", "name": "用友网络"},
                {"code": "600570.SH", "name": "恒生电子"},
                {"code": "300033.SZ", "name": "同花顺"},
            ],
            "行业应用软件": [
                {"code": "002410.SZ", "name": "广联达"},
                {"code": "300559.SZ", "name": "中航电测"},
                {"code": "688111.SH", "name": "金山办公"},
            ],
        },
        "IT服务": {
            "云计算": [
                {"code": "300230.SZ", "name": "永辉超市"},
                {"code": "002230.SZ", "name": "科大讯飞"},
                {"code": "300014.SZ", "name": "亿纬锂能"},
            ],
            "信息安全": [
                {"code": "300454.SZ", "name": "深信服"},
                {"code": "002049.SZ", "name": "紫光国微"},
                {"code": "300687.SZ", "name": "奥普特"},
            ],
        },
        "计算机设备": {
            "服务器存储": [
                {"code": "000977.SZ", "name": "浪潮信息"},
                {"code": "002252.SZ", "name": "上海莱士"},
                {"code": "603986.SH", "name": "兆易创新"},
            ],
        },
    },
    "传媒": {
        "互联网传媒": {
            "互联网信息服务": [
                {"code": "002555.SZ", "name": "三七互娱"},
                {"code": "300413.SZ", "name": "芒果超媒"},
                {"code": "002027.SZ", "name": "分众传媒"},
            ],
        },
        "出版": {
            "图书出版": [
                {"code": "601119.SH", "name": "中国出版"},
                {"code": "601002.SH", "name": "文化传媒"},
                {"code": "600237.SH", "name": "铜峰电子"},
            ],
        },
        "影视院线": {
            "电影院线": [
                {"code": "002739.SZ", "name": "万达电影"},
                {"code": "600977.SH", "name": "中国儿童"},
                {"code": "300027.SZ", "name": "华谊兄弟"},
            ],
        },
        "数字媒体": {
            "互联网内容": [
                {"code": "600804.SH", "name": "鹏博士"},
                {"code": "002364.SZ", "name": "中恒电气"},
                {"code": "300741.SZ", "name": "华统股份"},
            ],
        },
    },
    "通信": {
        "通信服务": {
            "基础电信运营": [
                {"code": "601728.SH", "name": "中国电信"},
                {"code": "600050.SH", "name": "中国联通"},
                {"code": "600941.SH", "name": "中国移动"},
            ],
        },
        "通信设备": {
            "光模块": [
                {"code": "300308.SZ", "name": "中际旭创"},
                {"code": "300502.SZ", "name": "新易盛"},
                {"code": "600498.SH", "name": "烽火通信"},
            ],
            "基站天线": [
                {"code": "002931.SZ", "name": "锐明技术"},
                {"code": "002897.SZ", "name": "意华股份"},
                {"code": "603869.SH", "name": "新智认知"},
            ],
        },
    },
    "煤炭": {
        "煤炭开采": {
            "动力煤": [
                {"code": "601088.SH", "name": "中国神华"},
                {"code": "601225.SH", "name": "陕西煤业"},
                {"code": "600188.SH", "name": "兖矿能源"},
            ],
            "炼焦煤": [
                {"code": "601666.SH", "name": "平煤股份"},
                {"code": "600997.SH", "name": "开滦股份"},
                {"code": "601918.SH", "name": "新集能源"},
            ],
        },
        "焦炭": {
            "焦化": [
                {"code": "600740.SH", "name": "山西焦化"},
                {"code": "600307.SH", "name": "酒钢宏兴"},
                {"code": "000937.SZ", "name": "冀中能源"},
            ],
        },
    },
    "石油石化": {
        "石油开采": {
            "上游勘探": [
                {"code": "601857.SH", "name": "中国石油"},
                {"code": "600871.SH", "name": "石化油服"},
                {"code": "002554.SZ", "name": "惠博普"},
            ],
        },
        "炼化及贸易": {
            "炼油化工": [
                {"code": "600028.SH", "name": "中国石化"},
                {"code": "600346.SH", "name": "恒力石化"},
                {"code": "002493.SZ", "name": "荣盛石化"},
            ],
        },
        "油气设备服务": {
            "油田服务": [
                {"code": "601808.SH", "name": "中海油服"},
                {"code": "002353.SZ", "name": "杰瑞股份"},
                {"code": "600583.SH", "name": "海油工程"},
            ],
        },
    },
    "电力设备": {
        "电源设备": {
            "风电设备": [
                {"code": "601941.SH", "name": "中国核电"},
                {"code": "600737.SH", "name": "中粮糖业"},
                {"code": "300484.SZ", "name": "中新赛克"},
            ],
            "光伏设备": [
                {"code": "688599.SH", "name": "天合光能"},
                {"code": "601012.SH", "name": "隆基绿能"},
                {"code": "002594.SZ", "name": "比亚迪"},
            ],
        },
        "电力设备": {
            "输变电设备": [
                {"code": "601877.SH", "name": "正泰电器"},
                {"code": "002266.SZ", "name": "浙富控股"},
                {"code": "601615.SH", "name": "明阳智能"},
            ],
        },
        "电池": {
            "锂电池": [
                {"code": "300750.SZ", "name": "宁德时代"},
                {"code": "002460.SZ", "name": "赣锋锂业"},
                {"code": "300014.SZ", "name": "亿纬锂能"},
            ],
            "储能": [
                {"code": "300274.SZ", "name": "阳光电源"},
                {"code": "002151.SZ", "name": "北斗星通"},
                {"code": "688819.SH", "name": "天能股份"},
            ],
        },
    },
    "国防军工": {
        "航空装备": {
            "军机产业链": [
                {"code": "000768.SZ", "name": "中航西飞"},
                {"code": "600760.SH", "name": "中航沈飞"},
                {"code": "002179.SZ", "name": "中航光电"},
            ],
            "航空发动机": [
                {"code": "600893.SH", "name": "航发动力"},
                {"code": "600765.SH", "name": "中航重机"},
                {"code": "002046.SZ", "name": "太极股份"},
            ],
        },
        "航天装备": {
            "卫星导航": [
                {"code": "600151.SH", "name": "航天机电"},
                {"code": "002151.SZ", "name": "北斗星通"},
                {"code": "600967.SH", "name": "内蒙华电"},
            ],
        },
        "地面兵装": {
            "坦克装甲": [
                {"code": "600862.SH", "name": "中航高科"},
                {"code": "000547.SZ", "name": "航天发展"},
                {"code": "600701.SH", "name": "厦门信达"},
            ],
        },
        "军工电子": {
            "军用雷达": [
                {"code": "688208.SH", "name": "道通科技"},
                {"code": "600990.SH", "name": "四创电子"},
                {"code": "002414.SZ", "name": "高德红外"},
            ],
        },
    },
    "机械设备": {
        "工程机械": {
            "工程机械整机": [
                {"code": "000157.SZ", "name": "中联重科"},
                {"code": "600031.SH", "name": "三一重工"},
                {"code": "000425.SZ", "name": "徐工机械"},
            ],
        },
        "通用设备": {
            "工业自动化": [
                {"code": "300124.SZ", "name": "汇川技术"},
                {"code": "688017.SH", "name": "绿的谐波"},
                {"code": "300450.SZ", "name": "先导智能"},
            ],
        },
        "专用设备": {
            "半导体设备": [
                {"code": "688012.SH", "name": "中微公司"},
                {"code": "688037.SH", "name": "芯源微"},
                {"code": "300604.SZ", "name": "长川科技"},
            ],
            "医疗设备": [
                {"code": "300760.SZ", "name": "迈瑞医疗"},
                {"code": "603192.SH", "name": "华安鑫创"},
                {"code": "688289.SH", "name": "灵动微电子"},
            ],
        },
        "自动化设备": {
            "机器人": [
                {"code": "300024.SZ", "name": "机器人"},
                {"code": "002903.SZ", "name": "开普云"},
                {"code": "300463.SZ", "name": "迈克生物"},
            ],
        },
    },
    "建筑材料": {
        "水泥": {
            "区域水泥": [
                {"code": "600585.SH", "name": "海螺水泥"},
                {"code": "000877.SZ", "name": "天山股份"},
                {"code": "600801.SH", "name": "华新水泥"},
            ],
        },
        "玻璃玻纤": {
            "玻璃制造": [
                {"code": "000786.SZ", "name": "北新建材"},
                {"code": "600586.SH", "name": "金晶科技"},
                {"code": "601136.SH", "name": "旗滨集团"},
            ],
            "玻璃纤维": [
                {"code": "600176.SH", "name": "中国巨石"},
                {"code": "605222.SH", "name": "起帆电缆"},
                {"code": "002006.SZ", "name": "精功科技"},
            ],
        },
        "装饰建材": {
            "陶瓷石材": [
                {"code": "000786.SZ", "name": "北新建材"},
                {"code": "002910.SZ", "name": "庄园牧场"},
                {"code": "002285.SZ", "name": "世联行"},
            ],
        },
    },
    "建筑装饰": {
        "基础建设": {
            "基建工程": [
                {"code": "601668.SH", "name": "中国建筑"},
                {"code": "601390.SH", "name": "中国中铁"},
                {"code": "601800.SH", "name": "中国交建"},
            ],
        },
        "房屋建设": {
            "房建施工": [
                {"code": "600170.SH", "name": "上海建工"},
                {"code": "002431.SZ", "name": "棕榈股份"},
                {"code": "601895.SH", "name": "中材国际"},
            ],
        },
        "专业工程": {
            "园林工程": [
                {"code": "002949.SZ", "name": "华阳国际"},
                {"code": "002154.SZ", "name": "报喜鸟"},
                {"code": "300070.SZ", "name": "碧水源"},
            ],
        },
        "装修装饰": {
            "家装工程": [
                {"code": "002376.SZ", "name": "亚太股份"},
                {"code": "300155.SZ", "name": "安居宝"},
                {"code": "002986.SZ", "name": "宇华教育"},
            ],
        },
    },
    "轻工制造": {
        "家具": {
            "家具制造": [
                {"code": "603833.SH", "name": "欧派家居"},
                {"code": "002801.SZ", "name": "视觉中国"},
                {"code": "300616.SZ", "name": "尚品宅配"},
            ],
        },
        "造纸": {
            "包装纸": [
                {"code": "002078.SZ", "name": "太阳纸业"},
                {"code": "600567.SH", "name": "山鹰国际"},
                {"code": "600966.SH", "name": "博汇纸业"},
            ],
            "文化纸": [
                {"code": "600308.SH", "name": "华泰股份"},
                {"code": "000488.SZ", "name": "晨鸣纸业"},
                {"code": "600079.SH", "name": "人福医药"},
            ],
        },
        "包装印刷": {
            "纸包装": [
                {"code": "002809.SZ", "name": "红墙股份"},
                {"code": "002540.SZ", "name": "亚太实业"},
                {"code": "600163.SH", "name": "中闽能源"},
            ],
        },
    },
    "社会服务": {
        "酒店餐饮": {
            "连锁餐饮": [
                {"code": "605108.SH", "name": "同庆楼"},
                {"code": "603043.SH", "name": "广州酒家"},
                {"code": "600258.SH", "name": "首旅酒店"},
            ],
            "酒店": [
                {"code": "600754.SH", "name": "锦江酒店"},
                {"code": "000428.SZ", "name": "华天酒店"},
                {"code": "002156.SZ", "name": "通富微电"},
            ],
        },
        "旅游及景区": {
            "景区运营": [
                {"code": "600054.SH", "name": "黄山旅游"},
                {"code": "000930.SZ", "name": "中粮科技"},
                {"code": "600098.SH", "name": "广州发展"},
            ],
        },
        "教育": {
            "教育培训": [
                {"code": "002607.SZ", "name": "中公教育"},
                {"code": "002230.SZ", "name": "科大讯飞"},
                {"code": "300532.SZ", "name": "今天国际"},
            ],
        },
        "专业服务": {
            "人力资源": [
                {"code": "002085.SZ", "name": "万丰奥威"},
                {"code": "300498.SZ", "name": "温氏股份"},
                {"code": "603869.SH", "name": "新智认知"},
            ],
        },
    },
    "综合": {
        "综合类": {
            "多元化经营": [
                {"code": "600770.SH", "name": "综艺股份"},
                {"code": "000009.SZ", "name": "中国宝安"},
                {"code": "600620.SH", "name": "天宸股份"},
            ],
        },
    },
    "环保": {
        "环境治理": {
            "固废处理": [
                {"code": "000826.SZ", "name": "启迪环境"},
                {"code": "300070.SZ", "name": "碧水源"},
                {"code": "601200.SH", "name": "上海环境"},
            ],
            "水处理": [
                {"code": "300070.SZ", "name": "碧水源"},
                {"code": "603568.SH", "name": "伟明环保"},
                {"code": "300172.SZ", "name": "中电环保"},
            ],
        },
        "环保设备": {
            "大气治理": [
                {"code": "002380.SZ", "name": "科远智慧"},
                {"code": "300190.SZ", "name": "维尔利"},
                {"code": "300056.SZ", "name": "中电环保"},
            ],
        },
    },
    "美容护理": {
        "个护用品": {
            "美妆护理": [
                {"code": "603605.SH", "name": "珀莱雅"},
                {"code": "300957.SZ", "name": "贝泰妮"},
                {"code": "603983.SH", "name": "丸美生物"},
            ],
        },
        "化妆品": {
            "专业化妆品": [
                {"code": "600318.SH", "name": "新力金融"},
                {"code": "002271.SZ", "name": "东方雨虹"},
                {"code": "300987.SZ", "name": "N华宝"},
            ],
        },
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
