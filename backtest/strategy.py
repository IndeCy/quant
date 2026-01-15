"""
策略基类模块 (Strategy Base Module)
定义交易策略的基础接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime
import pandas as pd


class BaseStrategy(ABC):
    """交易策略基类"""
    
    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.positions = {}  # {symbol: quantity}
        self.parameters = {}
        
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, date: datetime) -> Dict[str, int]:
        """
        生成交易信号
        
        Args:
            data: 市场数据
            date: 当前日期
            
        Returns:
            Dict[symbol, signal]: 交易信号字典
                signal > 0: 买入信号
                signal < 0: 卖出信号
                signal = 0: 无操作
        """
        pass
    
    def on_bar(self, date: datetime, data: pd.DataFrame) -> Dict[str, int]:
        """
        每个交易日的回调函数
        
        Args:
            date: 当前日期
            data: 当前市场数据
            
        Returns:
            Dict[symbol, signal]: 交易信号
        """
        return self.generate_signals(data, date)
    
    def set_parameters(self, **kwargs) -> None:
        """设置策略参数"""
        self.parameters.update(kwargs)
        
    def get_positions(self) -> Dict[str, int]:
        """获取当前持仓"""
        return self.positions.copy()
