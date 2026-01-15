"""
数据管理模块 (Data Management Module)
处理A股历史数据的加载、存储和访问
"""

import pandas as pd
from typing import Optional, List
from datetime import datetime


class DataManager:
    """A股数据管理器"""
    
    def __init__(self):
        self.data = {}
        
    def load_data(self, symbol: str, data: pd.DataFrame) -> None:
        """
        加载股票数据
        
        Args:
            symbol: 股票代码 (如 '000001.SZ')
            data: DataFrame包含 ['date', 'open', 'high', 'low', 'close', 'volume']
        """
        if not isinstance(data.index, pd.DatetimeIndex):
            if 'date' in data.columns:
                data = data.set_index('date')
            data.index = pd.to_datetime(data.index)
        
        self.data[symbol] = data.sort_index()
        
    def get_data(self, symbol: str, start_date: Optional[datetime] = None, 
                 end_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        获取股票数据
        
        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame: 股票数据
        """
        if symbol not in self.data:
            raise ValueError(f"Symbol {symbol} not found in data manager")
        
        data = self.data[symbol]
        
        if start_date:
            data = data[data.index >= start_date]
        if end_date:
            data = data[data.index <= end_date]
            
        return data
    
    def get_price(self, symbol: str, date: datetime, price_type: str = 'close') -> float:
        """
        获取特定日期的价格
        
        Args:
            symbol: 股票代码
            date: 日期
            price_type: 价格类型 ('open', 'high', 'low', 'close')
            
        Returns:
            float: 价格
        """
        data = self.get_data(symbol)
        
        if date not in data.index:
            # 如果日期不存在，返回最近的可用日期
            available_dates = data.index[data.index <= date]
            if len(available_dates) == 0:
                raise ValueError(f"No data available for {symbol} on or before {date}")
            date = available_dates[-1]
        
        return data.loc[date, price_type]
    
    def get_symbols(self) -> List[str]:
        """获取所有已加载的股票代码"""
        return list(self.data.keys())
