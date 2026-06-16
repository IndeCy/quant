"""
数据管理模块 (Data Management Module)
处理A股历史数据的加载、存储和访问
"""

import pandas as pd
from typing import Optional, List, Protocol
from datetime import datetime

from data.adjustment import AdjustType, normalize_adjust
from data.calendar import TradingCalendar
from data.cleaning import clean_daily_bars


class MarketDataSource(Protocol):
    """统一行情数据源接口，避免业务模块直接访问底层存储。"""

    def get_daily_bars(
        self,
        symbol: str,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
        adjust_policy: str | AdjustType = AdjustType.NONE,
    ) -> pd.DataFrame:
        """按复权口径读取统一 schema 日线。"""

    def get_trading_calendar(
        self,
        start_date: str | pd.Timestamp | None = None,
        end_date: str | pd.Timestamp | None = None,
    ) -> TradingCalendar:
        """返回数据源交易日历。"""


class DataManager:
    """A股数据管理器"""
    
    def __init__(
        self,
        data_source: MarketDataSource | None = None,
        default_adjust: str | AdjustType = AdjustType.NONE,
    ):
        self.data = {}
        self.adjustments = {}
        self.data_source = data_source
        self.default_adjust = normalize_adjust(default_adjust)
        
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

    def load_symbol(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        adjust: str | AdjustType | None = None,
    ) -> None:
        """
        通过统一数据源接口加载单只股票。

        DuckDB 等外部数据源必须在这里显式传入复权口径，确保信号价、成交价、
        估值价和基准价不会在同一次回测里混用不同价格口径。
        """
        if self.data_source is None:
            raise ValueError("DataManager 未配置外部数据源，不能 load_symbol")
        adjust_type = self.default_adjust if adjust is None else normalize_adjust(adjust)
        bars = self.data_source.get_daily_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            adjust_policy=adjust_type,
        )
        self.load_data(symbol, bars, adjust=adjust_type)
        
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

    def get_trading_calendar(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> TradingCalendar | None:
        """获取外部数据源交易日历；无外部数据源时返回 None。"""
        if self.data_source is None:
            return None
        return self.data_source.get_trading_calendar(start_date, end_date)

    def validate_single_adjustment_policy(self) -> AdjustType | None:
        """校验同一回测数据集中不能静默混用多个复权口径。"""
        if not self.adjustments:
            return None
        values = set(self.adjustments.values())
        if len(values) > 1:
            detail = {symbol: adjust.value for symbol, adjust in self.adjustments.items()}
            raise ValueError(f"同一次回测禁止混用复权口径: {detail}")
        return next(iter(values))
