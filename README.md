# 中国A股回测系统 (Chinese A-share Backtesting System)

一个专为中国A股市场设计的量化交易回测系统，支持多种策略和完整的性能分析。

## 特性 (Features)

- ✅ **完整的回测引擎**: 支持历史数据回测，模拟真实交易
- ✅ **A股交易规则**: 内置中国A股特有的交易规则（T+1、涨跌停、手续费等）
- ✅ **策略框架**: 灵活的策略基类，易于扩展自定义策略
- ✅ **交易成本模拟**: 包含佣金、印花税、过户费等真实交易成本
- ✅ **性能分析**: 计算收益率、夏普比率、最大回撤等关键指标
- ✅ **内置策略**: 提供多种常见交易策略示例
- ✅ **实时数据获取**: 集成 [a-stock-data](https://github.com/simonlin1212/a-stock-data) V3.2，覆盖行情/资金/行业/基础数据，零第三方数据封装依赖

## 系统架构 (Architecture)

```
backtest/
├── __init__.py          # 包初始化
├── data.py              # 数据管理模块
├── fetcher.py           # A股数据获取模块（集成 a-stock-data V3.2）
├── strategy.py          # 策略基类
├── strategies.py        # 示例策略集合
├── engine.py            # 回测引擎
└── analysis.py          # 性能分析模块
```

## 安装 (Installation)

```bash
# 克隆仓库
git clone https://github.com/IndeCy/quant.git
cd quant

# 安装依赖
pip install -r requirements.txt

# 或者安装为Python包（推荐）
pip install -e .
```

## 快速开始 (Quick Start)

### 基本使用

```python
from backtest.data import DataManager
from backtest.strategies import MovingAverageCrossStrategy
from backtest.engine import BacktestEngine
from backtest.analysis import PerformanceAnalyzer

# 1. 创建数据管理器并加载数据
data_manager = DataManager()
data_manager.load_data('000001.SZ', your_dataframe)

# 2. 创建交易策略
strategy = MovingAverageCrossStrategy('000001.SZ', short_window=5, long_window=20)

# 3. 初始化回测引擎
engine = BacktestEngine(
    data_manager=data_manager,
    strategy=strategy,
    initial_capital=1000000.0,  # 初始资金100万
    commission_rate=0.0003,      # 佣金率
    slippage=0.001               # 滑点
)

# 4. 运行回测
results = engine.run()

# 5. 分析结果
analyzer = PerformanceAnalyzer(results, engine.trades, 1000000.0)
analyzer.print_summary()
```

### 运行示例

```bash
cd examples
python simple_example.py
```

## 数据格式 (Data Format)

系统要求的数据格式为 pandas DataFrame，包含以下列：

```python
{
    'date': datetime,      # 日期（索引）
    'open': float,         # 开盘价
    'high': float,         # 最高价
    'low': float,          # 最低价
    'close': float,        # 收盘价
    'volume': int          # 成交量
}
```

### 使用内置数据获取模块（推荐）

`backtest.fetcher` 模块集成了 [a-stock-data](https://github.com/simonlin1212/a-stock-data) V3.2 的数据获取能力，
直连通达信/腾讯/东财，**零第三方数据封装依赖**，开箱即用。

```python
from backtest.data import DataManager
from backtest.fetcher import load_symbol, get_realtime_quote, get_industry_sectors, get_stock_info

dm = DataManager()

# ── 行情层：直接从通达信拉取历史K线并加载（不封IP）────────────────────────
load_symbol(dm, '000001', offset=250)   # 加载约1年日线，自动推断交易所后缀(.SZ)
load_symbol(dm, '600519', offset=500)   # 加载约2年日线
load_symbol(dm, '688017', offset=250)   # 科创板

# ── 行情层：腾讯财经实时报价（不封IP）────────────────────────────────────
quotes = get_realtime_quote(['600519', '000858', '300476'])
for code, q in quotes.items():
    print(f"{q['name']}({code}): {q['price']}元  PE={q['pe_ttm']:.1f}  PB={q['pb']:.2f}  市值={q['mcap_yi']:.0f}亿")

# ── 信号层：行业板块涨跌排行（东财，已内置限流）──────────────────────────
sectors = get_industry_sectors()
top5 = sorted(sectors, key=lambda x: x['change_pct'], reverse=True)[:5]
for s in top5:
    print(f"{s['name']}: {s['change_pct']:+.2f}%  ↑{s['up_count']} ↓{s['down_count']}")

# ── 基础数据：个股基本信息（东财，已内置限流）────────────────────────────
info = get_stock_info('600519')
print(f"{info['name']} 行业:{info['industry']} 上市:{info['list_date']}")
```

`backtest.fetcher` 数据能力一览：

| 函数 | 数据来源 | 封IP风险 | 说明 |
|------|---------|---------|------|
| `get_klines(symbol)` | mootdx（通达信） | 无 | 历史K线，多周期 |
| `load_symbol(dm, symbol)` | mootdx | 无 | 便捷函数：拉取并加载进 DataManager |
| `get_realtime_quote(codes)` | 腾讯财经 | 无 | 实时价/PE/PB/市值/换手率/涨跌停价 |
| `get_industry_sectors()` | 东财 push2 | 有（已限流） | 行业板块涨跌/上涨下跌家数/领涨股 |
| `get_fund_flow_minute(symbol)` | 东财 push2 | 有（已限流） | 分钟级主力/大单/小单净流入 |
| `get_stock_info(symbol)` | 东财 push2 | 有（已限流） | 行业/总股本/流通股/市值/上市日期 |

> 东财接口已内置串行限流（≥1s 间隔 + 随机抖动），批量调用时可调大 `backtest.fetcher.EM_MIN_INTERVAL`。

### 其他数据源参考

- **Tushare**: https://tushare.pro/
- **baostock**: http://baostock.com/

## 内置策略 (Built-in Strategies)

### 1. 买入持有策略 (Buy and Hold)
```python
from backtest.strategies import BuyAndHoldStrategy

strategy = BuyAndHoldStrategy('000001.SZ')
```

### 2. 双均线策略 (Moving Average Cross)
```python
from backtest.strategies import MovingAverageCrossStrategy

strategy = MovingAverageCrossStrategy('000001.SZ', 
                                      short_window=5, 
                                      long_window=20)
```

### 3. 动量策略 (Momentum)
```python
from backtest.strategies import MomentumStrategy

strategy = MomentumStrategy('000001.SZ', 
                           lookback_period=20,
                           buy_threshold=0.05,
                           sell_threshold=-0.03)
```

### 4. 均值回归策略 (Mean Reversion)
```python
from backtest.strategies import MeanReversionStrategy

strategy = MeanReversionStrategy('000001.SZ', 
                                 window=20, 
                                 num_std=2.0)
```

## 自定义策略 (Custom Strategy)

创建自定义策略只需继承 `BaseStrategy` 并实现 `generate_signals` 方法：

```python
from backtest.strategy import BaseStrategy
from typing import Dict
import pandas as pd
from datetime import datetime

class MyStrategy(BaseStrategy):
    """我的自定义策略"""
    
    def __init__(self, symbol: str):
        super().__init__(name="MyStrategy")
        self.symbol = symbol
        
    def generate_signals(self, data: Dict[str, pd.DataFrame], 
                        date: datetime) -> Dict[str, int]:
        """
        生成交易信号
        
        Returns:
            Dict[symbol, signal]: 
                signal > 0: 买入
                signal < 0: 卖出
                signal = 0: 不操作
        """
        if self.symbol not in data:
            return {}
        
        df = data[self.symbol]
        
        # 你的策略逻辑
        # ...
        
        return {self.symbol: signal_value}
```

## 交易成本 (Trading Costs)

系统模拟了中国A股的真实交易成本：

1. **佣金**: 双边收取，默认万分之三，最低5元
2. **印花税**: 卖出时收取千分之一
3. **过户费**: 双边收取，万分之0.2
4. **滑点**: 可配置的价格滑点

## 性能指标 (Performance Metrics)

系统计算以下性能指标：

- **总收益率**: 整个回测期间的总收益
- **年化收益率**: 按年度标准化的收益率
- **夏普比率**: 风险调整后收益
- **最大回撤**: 最大的资产下跌幅度
- **波动率**: 收益率的标准差（年化）
- **胜率**: 盈利交易日占比
- **交易次数**: 总交易笔数

## 行业分类与数据导入 (Industry & Data Import)

`IndustryManager` 提供三种方式扩充股票数据，无需修改源代码。

### 单只添加

```python
from backtest.industry import IndustryManager

manager = IndustryManager()
manager.add_stock("002339.SZ", "利通电子", "电子", "消费电子", "消费电子零部件")
```

### 从 CSV 文件批量导入

CSV 需包含表头：`code,name,level1,level2,level3`

```csv
code,name,level1,level2,level3
002339.SZ,利通电子,电子,消费电子,消费电子零部件
603893.SH,瑞芯微,电子,半导体,芯片设计
```

```python
added = manager.import_from_csv("my_stocks.csv")
print(f"新增 {added} 只股票")
```

### 从 JSON 文件批量导入

```json
[
  {"code": "002339.SZ", "name": "利通电子", "level1": "电子", "level2": "消费电子", "level3": "消费电子零部件"}
]
```

```python
added = manager.import_from_json("my_stocks.json")
```

### 与第三方数据源集成（akshare 示例）

安装 akshare 后，可将其行业分类数据导出为 CSV，再用 `import_from_csv` 导入：

```python
import akshare as ak
import pandas as pd

# 获取东方财富行业成分股（示例）
df = ak.stock_board_industry_cons_em(symbol="半导体")
df["level1"] = "电子"
df["level2"] = "半导体"
df["level3"] = "芯片设计"
df = df.rename(columns={"代码": "code", "名称": "name"})
df[["code", "name", "level1", "level2", "level3"]].to_csv("semiconductor.csv", index=False)

manager.import_from_csv("semiconductor.csv")
```

## 测试 (Testing)

运行单元测试：

```bash
python -m pytest tests/
```

或运行特定测试：

```bash
python tests/test_data.py
python tests/test_strategy.py
```

## 项目结构 (Project Structure)

```
quant/
├── README.md              # 项目文档
├── requirements.txt       # 依赖包
├── .gitignore            # Git忽略文件
├── backtest/             # 核心回测模块
│   ├── __init__.py
│   ├── data.py           # 数据管理
│   ├── strategy.py       # 策略基类
│   ├── strategies.py     # 示例策略
│   ├── engine.py         # 回测引擎
│   └── analysis.py       # 性能分析
├── examples/             # 使用示例
│   └── simple_example.py
└── tests/                # 单元测试
    ├── test_data.py
    └── test_strategy.py
```

## 注意事项 (Notes)

1. **A股交易规则**:
   - 买入卖出必须是100股（1手）的整数倍
   - T+1交易制度（暂未实现）
   - 涨跌停限制（暂未实现）

2. **数据质量**: 回测结果的准确性依赖于数据质量，建议使用可靠的数据源

3. **风险提示**: 历史表现不代表未来收益，实盘交易请谨慎

## 未来计划 (Roadmap)

- [ ] 支持T+1交易规则
- [ ] 实现涨跌停板限制
- [ ] 添加更多技术指标
- [ ] 支持多股票组合策略
- [ ] 实现参数优化功能
- [ ] 添加可视化界面
- [ ] 支持期货、期权等其他品种

## 贡献 (Contributing)

欢迎提交 Issue 和 Pull Request！

## 许可证 (License)

MIT License

## 联系方式 (Contact)

如有问题或建议，请提交 Issue。

---

**免责声明**: 本系统仅用于学习和研究目的，不构成投资建议。使用本系统进行实盘交易的风险由使用者自行承担。