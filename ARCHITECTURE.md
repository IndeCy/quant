# 系统架构文档 (System Architecture Documentation)

## 概述 (Overview)

本系统是一个专为中国A股市场设计的量化交易回测系统，采用模块化架构，各模块职责清晰，易于扩展和维护。

## 架构设计 (Architecture Design)

### 1. 模块划分 (Module Structure)

```
┌─────────────────────────────────────────────────────────┐
│                    用户接口层                             │
│            (Examples & User Scripts)                    │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────┴────────────────────────────────────────┐
│                 核心业务层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  策略模块  │  │ 回测引擎  │  │ 分析模块  │              │
│  │ Strategy │  │  Engine  │  │ Analysis │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└────────────────┬────────────────────────────────────────┘
                 │
┌────────────────┴────────────────────────────────────────┐
│                 数据层                                    │
│              ┌──────────┐                                │
│              │ 数据管理  │                                │
│              │   Data   │                                │
│              └──────────┘                                │
└─────────────────────────────────────────────────────────┘
```

### 2. 核心模块详解 (Core Modules)

#### 2.1 数据管理模块 (Data Module)

**文件**: `backtest/data.py`

**职责**:
- 管理股票历史数据的存储和访问
- 提供统一的数据接口
- 支持按日期范围查询

**核心类**:
- `DataManager`: 数据管理器，负责数据的加载、存储和查询

**关键方法**:
```python
load_data(symbol, data)          # 加载股票数据
get_data(symbol, start, end)     # 获取指定时间范围的数据
get_price(symbol, date, type)    # 获取特定日期的价格
get_symbols()                    # 获取所有已加载的股票代码
```

#### 2.2 策略模块 (Strategy Module)

**文件**: 
- `backtest/strategy.py` - 策略基类
- `backtest/strategies.py` - 内置策略实现

**职责**:
- 定义策略接口
- 实现具体的交易策略
- 生成买卖信号

**核心类**:
- `BaseStrategy`: 抽象基类，定义策略接口
- `BuyAndHoldStrategy`: 买入持有策略
- `MovingAverageCrossStrategy`: 双均线策略
- `MomentumStrategy`: 动量策略
- `MeanReversionStrategy`: 均值回归策略

**扩展方式**:
```python
class MyStrategy(BaseStrategy):
    def generate_signals(self, data, date):
        # 实现你的策略逻辑
        return signals
```

#### 2.3 回测引擎 (Backtest Engine)

**文件**: `backtest/engine.py`

**职责**:
- 模拟交易执行
- 管理投资组合
- 计算交易成本
- 记录交易历史

**核心类**:
- `Order`: 订单类
- `Portfolio`: 投资组合类
- `BacktestEngine`: 回测引擎主类

**交易流程**:
```
1. 获取当前市场数据
2. 调用策略生成信号
3. 根据信号创建订单
4. 应用滑点
5. 计算交易成本
6. 执行订单更新持仓
7. 记录交易和资产价值
```

#### 2.4 性能分析模块 (Analysis Module)

**文件**: `backtest/analysis.py`

**职责**:
- 计算绩效指标
- 生成报告
- 绘制图表

**核心类**:
- `PerformanceAnalyzer`: 绩效分析器

**关键指标**:
- 总收益率
- 年化收益率
- 夏普比率
- 最大回撤
- 波动率
- 胜率

## A股交易规则实现 (A-share Trading Rules)

### 1. 交易单位 (Trading Unit)
- 买入和卖出必须是100股（1手）的整数倍
- 实现位置: `engine.py` 订单执行部分

```python
# A股买入必须是100的整数倍（1手=100股）
quantity = (quantity // 100) * 100
```

### 2. 交易成本 (Trading Costs)

**佣金 (Commission)**:
- 双边收取
- 费率可配置（默认万分之三）
- 最低5元

**印花税 (Stamp Duty)**:
- 仅卖出时收取
- 费率: 千分之一

**过户费 (Transfer Fee)**:
- 双边收取
- 费率: 万分之0.2

实现代码:
```python
def calculate_commission(self, price, quantity):
    # 佣金
    commission = abs(price * quantity * self.commission_rate)
    commission = max(commission, 5.0)  # 最低5元
    
    # 印花税（仅卖出）
    if quantity < 0:
        stamp_duty = abs(price * quantity * 0.001)
        commission += stamp_duty
    
    # 过户费
    transfer_fee = abs(price * quantity * 0.00002)
    commission += transfer_fee
    
    return commission
```

### 3. 滑点 (Slippage)
- 买入时价格上浮
- 卖出时价格下降
- 比例可配置

## 数据流 (Data Flow)

```
用户脚本
  │
  ├─→ 加载历史数据 → DataManager
  │
  ├─→ 创建策略 → Strategy
  │
  ├─→ 初始化引擎 → BacktestEngine
  │                    │
  │                    ├─ 获取数据 ← DataManager
  │                    │
  │                    ├─ 生成信号 ← Strategy
  │                    │
  │                    ├─ 执行订单 → Portfolio
  │                    │
  │                    └─ 记录结果
  │
  └─→ 分析结果 → PerformanceAnalyzer
                     │
                     ├─ 计算指标
                     │
                     └─ 生成报告/图表
```

## 使用场景 (Use Cases)

### 场景1: 测试单一策略
```python
# 1. 加载数据
data_manager = DataManager()
data_manager.load_data('000001.SZ', df)

# 2. 创建策略
strategy = MovingAverageCrossStrategy('000001.SZ')

# 3. 运行回测
engine = BacktestEngine(data_manager, strategy)
results = engine.run()

# 4. 分析结果
analyzer = PerformanceAnalyzer(results, engine.trades, 1000000)
analyzer.print_summary()
```

### 场景2: 对比多个策略
```python
strategies = [
    Strategy1(),
    Strategy2(),
    Strategy3()
]

results = {}
for strategy in strategies:
    engine = BacktestEngine(data_manager, strategy)
    results[strategy.name] = engine.run()

# 对比分析
compare_strategies(results)
```

### 场景3: 参数优化
```python
best_params = None
best_return = -float('inf')

for short_window in range(5, 20):
    for long_window in range(20, 60):
        strategy = MovingAverageCrossStrategy(
            symbol, short_window, long_window
        )
        engine = BacktestEngine(data_manager, strategy)
        results = engine.run()
        
        total_return = get_return(results)
        if total_return > best_return:
            best_return = total_return
            best_params = (short_window, long_window)
```

## 扩展指南 (Extension Guide)

### 1. 添加新策略
继承 `BaseStrategy` 并实现 `generate_signals` 方法

### 2. 添加新的技术指标
在策略中计算，或创建独立的指标库

### 3. 添加新的绩效指标
扩展 `PerformanceAnalyzer` 类

### 4. 支持更多交易规则
修改 `BacktestEngine` 的订单执行逻辑

## 限制和注意事项 (Limitations)

1. **T+1规则**: 当前版本未实现T+1交易制度
2. **涨跌停**: 未实现涨跌停板限制
3. **停牌**: 未处理停牌情况
4. **分红配股**: 未处理分红配股调整
5. **单股票**: 当前主要支持单股票策略

## 性能优化建议 (Performance Tips)

1. 使用向量化操作而不是循环
2. 预先计算技术指标而不是每日重新计算
3. 合理设置回测时间范围
4. 使用适当的数据粒度

## 版本历史 (Version History)

- **v0.1.0** (2024-01): 初始版本
  - 基本回测框架
  - 4个示例策略
  - A股交易成本模拟
  - 性能分析功能

## 未来规划 (Future Plans)

- [ ] 实现T+1交易制度
- [ ] 添加涨跌停限制
- [ ] 支持多股票组合策略
- [ ] 参数优化框架
- [ ] 实时数据接入
- [ ] Web界面
