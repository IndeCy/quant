"""
简单使用示例
演示如何使用回测系统
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import DataManager
from backtest.strategies import MovingAverageCrossStrategy
from backtest.engine import BacktestEngine
from backtest.analysis import PerformanceAnalyzer


def generate_sample_data(symbol: str, start_date: str, end_date: str, 
                         initial_price: float = 100.0) -> pd.DataFrame:
    """
    生成示例数据用于演示
    
    实际使用时，应该从数据源（如tushare、akshare等）加载真实的A股数据
    """
    dates = pd.date_range(start=start_date, end=end_date, freq='B')  # B表示工作日
    
    # 生成随机价格数据
    np.random.seed(42)
    returns = np.random.randn(len(dates)) * 0.02  # 2%的日波动率
    
    # 添加趋势
    trend = np.linspace(0, 0.3, len(dates))
    returns = returns + trend / len(dates)
    
    prices = initial_price * (1 + returns).cumprod()
    
    # 生成OHLC数据
    data = pd.DataFrame({
        'date': dates,
        'open': prices * (1 + np.random.randn(len(dates)) * 0.005),
        'high': prices * (1 + np.abs(np.random.randn(len(dates))) * 0.01),
        'low': prices * (1 - np.abs(np.random.randn(len(dates))) * 0.01),
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, len(dates))
    })
    
    # 确保high是最高，low是最低
    data['high'] = data[['open', 'high', 'close']].max(axis=1)
    data['low'] = data[['open', 'low', 'close']].min(axis=1)
    
    return data


def main():
    """主函数"""
    print("=" * 60)
    print("中国A股回测系统示例")
    print("=" * 60)
    
    # 1. 创建数据管理器并加载数据
    print("\n步骤 1: 加载数据...")
    data_manager = DataManager()
    
    # 生成示例数据（实际使用时应从数据源加载）
    symbol = '000001.SZ'  # 平安银行
    data = generate_sample_data(symbol, '2023-01-01', '2023-12-31', initial_price=10.0)
    
    data_manager.load_data(symbol, data)
    print(f"已加载 {symbol} 的数据，共 {len(data)} 个交易日")
    
    # 2. 创建策略
    print("\n步骤 2: 创建交易策略...")
    strategy = MovingAverageCrossStrategy(symbol, short_window=5, long_window=20)
    print(f"策略: {strategy.name}")
    print(f"参数: 短期均线={5}, 长期均线={20}")
    
    # 3. 创建回测引擎
    print("\n步骤 3: 初始化回测引擎...")
    engine = BacktestEngine(
        data_manager=data_manager,
        strategy=strategy,
        initial_capital=1000000.0,  # 100万初始资金
        commission_rate=0.0003,      # 万分之三的佣金
        slippage=0.001               # 0.1%的滑点
    )
    
    # 4. 运行回测
    print("\n步骤 4: 运行回测...")
    results = engine.run()
    
    # 5. 分析结果
    print("\n步骤 5: 分析回测结果...")
    analyzer = PerformanceAnalyzer(
        daily_values=results,
        trades=engine.trades,
        initial_capital=1000000.0
    )
    
    # 打印绩效报告
    analyzer.print_summary()
    
    # 保存交易记录
    if len(engine.trades) > 0:
        trades_df = pd.DataFrame(engine.trades)
        print("最近10笔交易:")
        print(trades_df.head(10).to_string())
    
    print("\n回测完成！")
    print("\n提示: 实际使用时，请从tushare、akshare等数据源加载真实的A股数据")


if __name__ == '__main__':
    main()
