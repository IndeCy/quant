"""
回测引擎模块 (Backtesting Engine Module)
核心回测引擎，模拟交易执行
"""

from typing import Dict, Optional, List
from datetime import datetime
import pandas as pd
import numpy as np

from .data import DataManager
from .strategy import BaseStrategy


class Order:
    """订单类"""
    
    def __init__(self, symbol: str, quantity: int, price: float, 
                 date: datetime, order_type: str = 'market'):
        self.symbol = symbol
        self.quantity = quantity  # 正数为买入，负数为卖出
        self.price = price
        self.date = date
        self.order_type = order_type
        self.filled = False
        
    def __repr__(self):
        action = "BUY" if self.quantity > 0 else "SELL"
        return f"Order({action} {abs(self.quantity)} {self.symbol} @ {self.price:.2f})"


class Portfolio:
    """投资组合类"""
    
    def __init__(self, initial_capital: float = 1000000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {symbol: quantity}
        self.history = []
        
    def update_position(self, symbol: str, quantity: int, price: float, 
                       commission: float = 0.0) -> bool:
        """
        更新持仓
        
        Args:
            symbol: 股票代码
            quantity: 数量变化（正数买入，负数卖出）
            price: 成交价格
            commission: 手续费
            
        Returns:
            bool: 是否成功
        """
        cost = quantity * price + commission
        
        # 检查是否有足够的现金（买入时）或股票（卖出时）
        if quantity > 0:  # 买入
            if self.cash < cost:
                return False
        else:  # 卖出
            current_position = self.positions.get(symbol, 0)
            if current_position < abs(quantity):
                return False
        
        # 更新现金
        self.cash -= cost
        
        # 更新持仓
        current_position = self.positions.get(symbol, 0)
        new_position = current_position + quantity
        
        if new_position == 0:
            del self.positions[symbol]
        else:
            self.positions[symbol] = new_position
            
        return True
    
    def get_total_value(self, prices: Dict[str, float]) -> float:
        """
        计算总资产价值
        
        Args:
            prices: 当前价格字典 {symbol: price}
            
        Returns:
            float: 总资产
        """
        position_value = sum(
            self.positions.get(symbol, 0) * prices.get(symbol, 0)
            for symbol in self.positions
        )
        return self.cash + position_value


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, data_manager: DataManager, strategy: BaseStrategy,
                 initial_capital: float = 1000000.0,
                 commission_rate: float = 0.0003,
                 slippage: float = 0.0):
        """
        初始化回测引擎
        
        Args:
            data_manager: 数据管理器
            strategy: 交易策略
            initial_capital: 初始资金
            commission_rate: 手续费率（双边）
            slippage: 滑点（比例）
        """
        self.data_manager = data_manager
        self.strategy = strategy
        self.portfolio = Portfolio(initial_capital)
        self.commission_rate = commission_rate
        self.slippage = slippage
        
        self.trades = []
        self.daily_values = []
        
    def calculate_commission(self, price: float, quantity: int) -> float:
        """
        计算手续费（包含印花税）
        
        中国A股交易费用：
        - 佣金：双边，最低5元
        - 印花税：卖出时收取0.1%
        - 过户费：双边，0.002%
        """
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
    
    def execute_order(self, order: Order) -> bool:
        """
        执行订单
        
        Args:
            order: 订单对象
            
        Returns:
            bool: 是否成功执行
        """
        # 应用滑点
        if order.quantity > 0:  # 买入
            execution_price = order.price * (1 + self.slippage)
        else:  # 卖出
            execution_price = order.price * (1 - self.slippage)
        
        # 计算手续费
        commission = self.calculate_commission(execution_price, order.quantity)
        
        # 更新持仓
        success = self.portfolio.update_position(
            order.symbol, order.quantity, execution_price, commission
        )
        
        if success:
            order.filled = True
            self.trades.append({
                'date': order.date,
                'symbol': order.symbol,
                'quantity': order.quantity,
                'price': execution_price,
                'commission': commission
            })
            
        return success

    def _execute_target_weight_orders(
        self,
        target_weights: Dict[str, float],
        current_prices: Dict[str, float],
        current_date: datetime,
    ) -> None:
        """按目标权重调仓，适合轮动策略做等权持仓。"""
        total_value = self.portfolio.get_total_value(current_prices)

        # 先卖出超配或目标为0的持仓，释放现金后再买入欠配标的。
        sell_orders: List[Order] = []
        buy_orders: List[Order] = []
        for symbol, target_weight in target_weights.items():
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            current_quantity = self.portfolio.positions.get(symbol, 0)
            current_value = current_quantity * price
            target_value = total_value * max(target_weight, 0.0)
            value_diff = target_value - current_value
            quantity = int(abs(value_diff) / price)
            quantity = (quantity // 100) * 100
            if quantity < 100:
                continue
            if value_diff < 0:
                sell_orders.append(Order(symbol, -min(quantity, current_quantity), price, current_date))
            else:
                buy_orders.append(Order(symbol, quantity, price, current_date))

        for order in sell_orders:
            if abs(order.quantity) >= 100:
                self.execute_order(order)
        for order in buy_orders:
            execution_price = order.price * (1 + self.slippage)
            while order.quantity >= 100:
                commission = self.calculate_commission(execution_price, order.quantity)
                if self.portfolio.cash >= order.quantity * execution_price + commission:
                    break
                order.quantity -= 100
            if order.quantity < 100:
                continue
            self.execute_order(order)

    def _is_target_weight_signal(self, signals: Dict[str, int | float]) -> bool:
        """判断信号是否为目标权重格式。"""
        if not signals:
            return False
        return all(isinstance(signal, float) and -1.0 <= signal <= 1.0 for signal in signals.values())
    
    def run(self, start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        运行回测
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame: 回测结果
        """
        # 获取所有交易日
        symbols = self.data_manager.get_symbols()
        if not symbols:
            raise ValueError("No data loaded in data manager")
        
        # 使用第一个股票的日期作为交易日历
        dates = self.data_manager.get_data(symbols[0], start_date, end_date).index
        
        print(f"开始回测: {dates[0]} 到 {dates[-1]}")
        print(f"初始资金: ¥{self.portfolio.initial_capital:,.2f}")
        
        for current_date in dates:
            # 获取当前所有股票的数据
            current_data = {}
            current_prices = {}
            
            for symbol in symbols:
                try:
                    data = self.data_manager.get_data(symbol, end_date=current_date)
                    if len(data) > 0 and current_date in data.index:
                        current_data[symbol] = data
                        current_prices[symbol] = data.loc[current_date, 'close']
                except Exception:
                    continue
            
            if not current_data:
                continue
            
            # 生成交易信号
            signals = self.strategy.on_bar(current_date, current_data)

            if self._is_target_weight_signal(signals):
                self._execute_target_weight_orders(signals, current_prices, current_date)
                total_value = self.portfolio.get_total_value(current_prices)
                self.daily_values.append({
                    'date': current_date,
                    'total_value': total_value,
                    'cash': self.portfolio.cash,
                    'positions_value': total_value - self.portfolio.cash
                })
                continue
            
            # 执行交易
            for symbol, signal in signals.items():
                if signal == 0 or symbol not in current_prices:
                    continue
                
                current_price = current_prices[symbol]
                current_position = self.portfolio.positions.get(symbol, 0)
                
                if signal > 0:  # 买入信号
                    # 计算可买入的数量（使用可用现金的一定比例）
                    max_quantity = int(self.portfolio.cash * 0.95 / (current_price * (1 + self.slippage + self.commission_rate)))
                    quantity = min(signal, max_quantity)
                    
                    # A股买入必须是100的整数倍（1手=100股）
                    quantity = (quantity // 100) * 100
                    
                    if quantity >= 100:
                        order = Order(symbol, quantity, current_price, current_date)
                        self.execute_order(order)
                        
                elif signal < 0:  # 卖出信号
                    # 卖出持仓
                    if current_position > 0:
                        quantity = min(abs(signal), current_position)
                        # A股卖出必须是100的整数倍
                        quantity = (quantity // 100) * 100
                        
                        if quantity >= 100:
                            order = Order(symbol, -quantity, current_price, current_date)
                            self.execute_order(order)
            
            # 记录每日资产价值
            total_value = self.portfolio.get_total_value(current_prices)
            self.daily_values.append({
                'date': current_date,
                'total_value': total_value,
                'cash': self.portfolio.cash,
                'positions_value': total_value - self.portfolio.cash
            })
        
        print(f"回测完成！")
        return pd.DataFrame(self.daily_values).set_index('date')
