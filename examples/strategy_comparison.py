"""
多策略对比示例
演示如何对比多个策略的表现
"""

import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import DataManager
from backtest.strategies import (
    BuyAndHoldStrategy, 
    MovingAverageCrossStrategy,
    MomentumStrategy,
    MeanReversionStrategy
)
from backtest.engine import BacktestEngine
from backtest.analysis import PerformanceAnalyzer


def generate_sample_data(symbol: str, start_date: str, end_date: str, 
                         initial_price: float = 100.0) -> pd.DataFrame:
    """生成示例数据"""
    dates = pd.date_range(start=start_date, end=end_date, freq='B')
    
    np.random.seed(42)
    returns = np.random.randn(len(dates)) * 0.02
    trend = np.linspace(0, 0.3, len(dates))
    returns = returns + trend / len(dates)
    
    prices = initial_price * (1 + returns).cumprod()
    
    data = pd.DataFrame({
        'date': dates,
        'open': prices * (1 + np.random.randn(len(dates)) * 0.005),
        'high': prices * (1 + np.abs(np.random.randn(len(dates))) * 0.01),
        'low': prices * (1 - np.abs(np.random.randn(len(dates))) * 0.01),
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, len(dates))
    })
    
    data['high'] = data[['open', 'high', 'close']].max(axis=1)
    data['low'] = data[['open', 'low', 'close']].min(axis=1)
    
    return data


def run_strategy_comparison():
    """运行多个策略并对比结果"""
    print("=" * 70)
    print("多策略对比示例")
    print("=" * 70)
    
    # 准备数据
    symbol = '000001.SZ'
    data = generate_sample_data(symbol, '2023-01-01', '2023-12-31', initial_price=10.0)
    
    # 定义要测试的策略
    strategies = [
        ('买入持有', BuyAndHoldStrategy(symbol)),
        ('双均线(5,20)', MovingAverageCrossStrategy(symbol, 5, 20)),
        ('双均线(10,30)', MovingAverageCrossStrategy(symbol, 10, 30)),
        ('动量策略', MomentumStrategy(symbol, lookback_period=20)),
        ('均值回归', MeanReversionStrategy(symbol, window=20))
    ]
    
    # 存储结果
    results = []
    
    print(f"\n正在测试 {len(strategies)} 个策略...\n")
    
    for name, strategy in strategies:
        print(f"运行策略: {name}")
        
        # 创建新的数据管理器
        data_manager = DataManager()
        data_manager.load_data(symbol, data)
        
        # 创建回测引擎
        engine = BacktestEngine(
            data_manager=data_manager,
            strategy=strategy,
            initial_capital=1000000.0,
            commission_rate=0.0003,
            slippage=0.001
        )
        
        # 运行回测
        daily_values = engine.run()
        
        # 分析结果
        analyzer = PerformanceAnalyzer(
            daily_values=daily_values,
            trades=engine.trades,
            initial_capital=1000000.0
        )
        
        summary = analyzer.get_summary()
        summary['策略名称'] = name
        results.append(summary)
        
        print(f"  ✓ 完成\n")
    
    # 创建结果对比表
    results_df = pd.DataFrame(results)
    results_df = results_df[['策略名称', '总收益率', '年化收益率', '夏普比率', 
                             '最大回撤', '波动率', '胜率', '交易次数']]
    
    # 格式化显示
    print("\n" + "=" * 70)
    print("策略对比结果")
    print("=" * 70)
    print(results_df.to_string(index=False, float_format=lambda x: f'{x:.2%}' 
                               if abs(x) < 10 else f'{x:.2f}'))
    print("=" * 70)
    
    # 找出最佳策略
    print("\n最佳策略指标:")
    print(f"  最高收益率: {results_df.loc[results_df['总收益率'].idxmax(), '策略名称']}")
    print(f"  最高夏普比率: {results_df.loc[results_df['夏普比率'].idxmax(), '策略名称']}")
    print(f"  最小回撤: {results_df.loc[results_df['最大回撤'].idxmax(), '策略名称']}")
    
    print("\n对比完成！")


if __name__ == '__main__':
    run_strategy_comparison()
