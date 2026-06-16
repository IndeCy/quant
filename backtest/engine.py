"""
回测引擎模块 (Backtesting Engine Module)
核心回测引擎，模拟交易执行
"""

from typing import Dict, Optional, List
from datetime import datetime
import pandas as pd
import numpy as np

from data.calendar import TradingCalendar
from .data import DataManager
from .execution_model import ExecutionModel, ExecutionResult
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
                 slippage: float = 0.0,
                 execution_model: ExecutionModel | None = None,
                 trading_calendar: TradingCalendar | None = None):
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
        self.execution_model = execution_model or ExecutionModel(
            commission_rate=commission_rate,
            slippage_bps=slippage * 10000,
        )
        self.trading_calendar = trading_calendar or TradingCalendar()
        
        self.trades = []
        self.daily_values = []
        self.failed_trades = []
        self.failed_trade_count = 0
        self.pending_signals = []
        
    def calculate_commission(self, price: float, quantity: int) -> float:
        """兼容旧接口：费用计算委托给统一成交模型。"""
        return self.execution_model.calculate_cash_fee(price, quantity)
    
    def execute_order(self, order: Order) -> bool:
        """
        执行订单
        
        Args:
            order: 订单对象
            
        Returns:
            bool: 是否成功执行
        """
        # 兼容外部直接调用 execute_order 的旧代码：order.price 已视为成交价。
        commission = self.calculate_commission(order.price, order.quantity)
        success = self.portfolio.update_position(order.symbol, order.quantity, order.price, commission)
        
        if success:
            order.filled = True
            self.trades.append({
                'date': order.date,
                'symbol': order.symbol,
                'quantity': order.quantity,
                'price': order.price,
                'commission': commission,
                'stamp_tax': 0.0,
                'slippage_cost': 0.0,
                'total_fee': commission,
            })
            
        return success

    def _all_available_dates(self) -> list[pd.Timestamp]:
        """基于已加载行情形成回测可推进的交易日列表。"""
        dates: set[pd.Timestamp] = set()
        for symbol in self.data_manager.get_symbols():
            data = self.data_manager.get_data(symbol)
            dates.update(pd.Timestamp(index).normalize() for index in data.index)
        return sorted(day for day in dates if self.trading_calendar.is_trading_day(day))

    def _get_bar(self, symbol: str, current_date: pd.Timestamp) -> Optional[pd.Series]:
        """读取某标的某交易日K线，不存在则返回 None。"""
        try:
            data = self.data_manager.get_data(symbol)
        except ValueError:
            return None
        if current_date not in data.index:
            return None
        return data.loc[current_date]

    def _get_current_data_and_prices(
        self,
        symbols: List[str],
        current_date: pd.Timestamp,
    ) -> tuple[Dict[str, pd.DataFrame], Dict[str, float]]:
        """获取策略可见数据和当日收盘估值价格。"""
        current_data = {}
        current_prices = {}
        for symbol in symbols:
            try:
                data = self.data_manager.get_data(symbol, end_date=current_date)
            except Exception:
                continue
            if len(data) == 0 or current_date not in data.index:
                continue
            current_data[symbol] = data
            close_price = pd.to_numeric(data.loc[current_date, "close"], errors="coerce")
            if not pd.isna(close_price) and float(close_price) > 0:
                current_prices[symbol] = float(close_price)
        return current_data, current_prices

    def _record_failed_trade(
        self,
        symbol: str,
        quantity: int,
        execution_date: pd.Timestamp,
        signal_date: pd.Timestamp,
        reason: str,
    ) -> None:
        """记录未成交原因，便于回测后做可信度分析。"""
        self.failed_trade_count += 1
        self.failed_trades.append(
            {
                "date": execution_date,
                "signal_date": signal_date,
                "symbol": symbol,
                "quantity": quantity,
                "reason": reason,
            }
        )

    def _apply_execution_result(
        self,
        result: ExecutionResult,
        signal_date: pd.Timestamp,
    ) -> bool:
        """把成交模型结果落到账户，并记录交易明细。"""
        cash_fee = result.commission + result.stamp_tax
        success = self.portfolio.update_position(
            result.symbol,
            result.quantity,
            result.price,
            cash_fee,
        )
        if not success:
            self._record_failed_trade(result.symbol, result.quantity, result.date, signal_date, "portfolio_rejected")
            return False

        self.trades.append(
            {
                "date": result.date,
                "signal_date": signal_date,
                "symbol": result.symbol,
                "quantity": result.quantity,
                "price": result.price,
                "raw_price": result.raw_price,
                "commission": cash_fee,
                "broker_commission": result.commission,
                "stamp_tax": result.stamp_tax,
                "slippage_cost": result.slippage_cost,
                "total_fee": result.total_fee,
            }
        )
        return True

    def _simulate_order(
        self,
        symbol: str,
        quantity: int,
        execution_date: pd.Timestamp,
        signal_date: pd.Timestamp,
    ) -> ExecutionResult | None:
        """统一调用成交模型并处理无行情场景。"""
        bar = self._get_bar(symbol, execution_date)
        if bar is None:
            self._record_failed_trade(symbol, quantity, execution_date, signal_date, "missing_bar")
            return None
        result = self.execution_model.simulate_order(symbol, quantity, bar, execution_date)
        if not result.success:
            self._record_failed_trade(symbol, quantity, execution_date, signal_date, result.reason)
            return None
        return result

    def _fit_buy_quantity(
        self,
        symbol: str,
        quantity: int,
        execution_date: pd.Timestamp,
        signal_date: pd.Timestamp,
    ) -> ExecutionResult | None:
        """按100股一手向下调整买入数量，确保现金足够支付成交价和现金费用。"""
        adjusted_quantity = (quantity // 100) * 100
        while adjusted_quantity >= 100:
            result = self._simulate_order(symbol, adjusted_quantity, execution_date, signal_date)
            if result is None:
                return None
            required_cash = result.quantity * result.price + result.commission + result.stamp_tax
            if self.portfolio.cash >= required_cash:
                return result
            adjusted_quantity -= 100
        return None

    def _execute_target_weight_orders(
        self,
        target_weights: Dict[str, float],
        current_date: datetime,
        signal_date: pd.Timestamp,
    ) -> None:
        """按目标权重调仓，适合轮动策略做等权持仓。"""
        current_prices = {}
        for symbol in set(target_weights) | set(self.portfolio.positions):
            bar = self._get_bar(symbol, pd.Timestamp(current_date))
            if bar is None:
                continue
            price = pd.to_numeric(bar.get(self.execution_model.execution_price_type), errors="coerce")
            if not pd.isna(price) and float(price) > 0:
                current_prices[symbol] = float(price)
        total_value = self.portfolio.get_total_value(current_prices)

        # 先卖出超配或目标为0的持仓，释放现金后再买入欠配标的。
        sell_orders: List[tuple[str, int]] = []
        buy_orders: List[tuple[str, int]] = []
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
                sell_orders.append((symbol, -min(quantity, current_quantity)))
            else:
                buy_orders.append((symbol, quantity))

        for symbol, quantity in sell_orders:
            if abs(quantity) >= 100:
                result = self._simulate_order(symbol, quantity, pd.Timestamp(current_date), signal_date)
                if result is not None:
                    self._apply_execution_result(result, signal_date)
        for symbol, quantity in buy_orders:
            result = self._fit_buy_quantity(symbol, quantity, pd.Timestamp(current_date), signal_date)
            if result is not None:
                self._apply_execution_result(result, signal_date)

    def _is_target_weight_signal(self, signals: Dict[str, int | float]) -> bool:
        """判断信号是否为目标权重格式。"""
        if not signals:
            return False
        return all(isinstance(signal, float) and -1.0 <= signal <= 1.0 for signal in signals.values())

    def _schedule_signals(
        self,
        signal_date: pd.Timestamp,
        signals: Dict[str, int | float],
        run_calendar: TradingCalendar,
    ) -> None:
        """把 T 日策略信号排入 T+lag 交易日成交队列。"""
        if not signals:
            return
        execution_date = run_calendar.next_trading_day(signal_date, self.execution_model.execution_lag)
        if execution_date is None:
            return
        self.pending_signals.append(
            {
                "signal_date": pd.Timestamp(signal_date),
                "execution_date": execution_date,
                "signals": dict(signals),
                "is_target_weight": self._is_target_weight_signal(signals),
            }
        )

    def _execute_pending_signals(self, current_date: pd.Timestamp) -> None:
        """执行到达成交日的挂起信号。"""
        remaining = []
        for item in self.pending_signals:
            if item["execution_date"] != current_date:
                remaining.append(item)
                continue
            signal_date = item["signal_date"]
            signals = item["signals"]
            if item["is_target_weight"]:
                self._execute_target_weight_orders(signals, current_date, signal_date)
                continue

            for symbol, signal in signals.items():
                if signal == 0:
                    continue
                current_position = self.portfolio.positions.get(symbol, 0)
                if signal > 0:
                    quantity = int(signal)
                    result = self._fit_buy_quantity(symbol, quantity, current_date, signal_date)
                    if result is not None:
                        self._apply_execution_result(result, signal_date)
                elif signal < 0 and current_position > 0:
                    quantity = min(abs(int(signal)), current_position)
                    quantity = (quantity // 100) * 100
                    if quantity >= 100:
                        result = self._simulate_order(symbol, -quantity, current_date, signal_date)
                        if result is not None:
                            self._apply_execution_result(result, signal_date)
        self.pending_signals = remaining
    
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
        symbols = self.data_manager.get_symbols()
        if not symbols:
            raise ValueError("No data loaded in data manager")
        self.data_manager.validate_single_adjustment_policy()

        available_dates = self._all_available_dates()
        if start_date:
            available_dates = [day for day in available_dates if day >= pd.Timestamp(start_date)]
        if end_date:
            available_dates = [day for day in available_dates if day <= pd.Timestamp(end_date)]
        if not available_dates:
            raise ValueError("No trading dates available for backtest")
        run_calendar = TradingCalendar(available_dates)
        dates = run_calendar.trading_days(available_dates[0], available_dates[-1])
        
        print(f"开始回测: {dates[0]} 到 {dates[-1]}")
        print(f"初始资金: ¥{self.portfolio.initial_capital:,.2f}")
        
        for current_date in dates:
            # 先执行此前信号在当前交易日触发的订单，再生成收盘后的新信号。
            self._execute_pending_signals(current_date)
            current_data, current_prices = self._get_current_data_and_prices(symbols, current_date)
            
            if not current_data:
                continue
            
            # 生成交易信号
            signals = self.strategy.on_bar(current_date, current_data)
            self._schedule_signals(current_date, signals, run_calendar)
            
            # 记录每日资产价值
            total_value = self.portfolio.get_total_value(current_prices)
            self.daily_values.append({
                'date': current_date,
                'total_value': total_value,
                'cash': self.portfolio.cash,
                'positions_value': total_value - self.portfolio.cash,
                'failed_trade_count': self.failed_trade_count,
            })
        
        print(f"回测完成！")
        return pd.DataFrame(self.daily_values).set_index('date')
