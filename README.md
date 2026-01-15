# 中国A股回测系统 (Chinese A-share Backtesting System)

一个专为中国A股市场设计的量化交易回测系统，支持多种策略和完整的性能分析。

## 特性 (Features)

- ✅ **完整的回测引擎**: 支持历史数据回测，模拟真实交易
- ✅ **A股交易规则**: 内置中国A股特有的交易规则（T+1、涨跌停、手续费等）
- ✅ **策略框架**: 灵活的策略基类，易于扩展自定义策略
- ✅ **交易成本模拟**: 包含佣金、印花税、过户费等真实交易成本
- ✅ **性能分析**: 计算收益率、夏普比率、最大回撤等关键指标
- ✅ **内置策略**: 提供多种常见交易策略示例

## 系统架构 (Architecture)

```
backtest/
├── __init__.py          # 包初始化
├── data.py              # 数据管理模块
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

### 数据源建议

可以使用以下数据源获取A股历史数据：

- **Tushare**: https://tushare.pro/
- **AkShare**: https://github.com/akfamily/akshare
- **baostock**: http://baostock.com/

示例（使用AkShare）：

```python
import akshare as ak

# 获取股票历史数据
stock_data = ak.stock_zh_a_hist(symbol="000001", period="daily", 
                                 start_date="20230101", end_date="20231231")
# 重命名列以匹配系统格式
stock_data.columns = ['date', 'open', 'close', 'high', 'low', 'volume', ...]
```

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