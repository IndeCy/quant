"""
数据管理模块 (Data Management Module)
处理A股历史数据的加载、存储和访问
"""

import pandas as pd
from typing import Optional, List
from datetime import datetime

from data.adjustment import AdjustType, normalize_adjust
from data.cleaning import clean_daily_bars


class DataManager:
    """A股数据管理器"""
    
    def __init__(self):
        self.data = {}
        self.adjustments = {}
        
    def load_data(self, symbol: str, data: pd.DataFrame, adjust: str | AdjustType = AdjustType.NONE) -> None:
        """
        加载股票数据
        
        Args:
            symbol: 股票代码 (如 '000001.SZ')
            data: DataFrame包含 ['date', 'open', 'high', 'low', 'close', 'volume']
            adjust: 复权口径，支持 none/qfq/hfq
        """
        adjust_type = normalize_adjust(adjust)
        # 统一日K字段和日期索引，后续回测统一按 trade_date 推进。
        cleaned = clean_daily_bars(data, symbol=symbol)
        cleaned.attrs["adjust"] = adjust_type.value
        self.data[symbol] = cleaned
        self.adjustments[symbol] = adjust_type
        
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

    def get_adjust(self, symbol: str) -> AdjustType:
        """获取某标的当前加载数据的复权口径。"""
        if symbol not in self.adjustments:
            raise ValueError(f"Symbol {symbol} not found in data manager")
        return self.adjustments[symbol]

    def get_adjustments(self) -> dict[str, AdjustType]:
        """获取所有已加载标的的复权口径。"""
        return self.adjustments.copy()

    def validate_single_adjustment_policy(self) -> AdjustType | None:
        """校验同一回测数据集中不能静默混用多个复权口径。"""
        if not self.adjustments:
            return None
        values = set(self.adjustments.values())
        if len(values) > 1:
            detail = {symbol: adjust.value for symbol, adjust in self.adjustments.items()}
            raise ValueError(f"同一次回测禁止混用复权口径: {detail}")
        return next(iter(values))
