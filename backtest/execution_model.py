"""
成交模型

统一处理信号日和成交日的分离、成交价格、交易费用与不可交易拦截。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ExecutionResult:
    """单笔订单模拟成交结果。"""

    success: bool
    symbol: str
    quantity: int
    date: pd.Timestamp
    price: float = 0.0
    raw_price: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    slippage_cost: float = 0.0
    total_fee: float = 0.0
    reason: str = ""


class ExecutionModel:
    """低频A股回测成交模型，默认 T 日信号、T+1 交易日成交。"""

    def __init__(
        self,
        signal_price_type: str = "close",
        execution_lag: int = 1,
        execution_price_type: str = "open",
        commission_rate: float = 0.0003,
        stamp_tax_rate: float = 0.001,
        slippage_bps: float = 0.0,
        min_commission: float = 5.0,
    ):
        if execution_lag < 1:
            raise ValueError("默认禁止当日信号当日成交，execution_lag 必须大于等于1")
        self.signal_price_type = signal_price_type
        self.execution_lag = execution_lag
        self.execution_price_type = execution_price_type
        self.commission_rate = commission_rate
        self.stamp_tax_rate = stamp_tax_rate
        self.slippage_bps = slippage_bps
        self.min_commission = min_commission

    @property
    def slippage_rate(self) -> float:
        """滑点 bps 转比例。"""
        return self.slippage_bps / 10000.0

    def calculate_commission(self, price: float, quantity: int) -> float:
        """计算券商佣金，买卖双边收取。"""
        commission = abs(price * quantity * self.commission_rate)
        if self.min_commission > 0:
            commission = max(commission, self.min_commission)
        return commission

    def calculate_cash_fee(self, price: float, quantity: int) -> float:
        """计算会真实影响现金的交易费用，包含佣金和卖出印花税。"""
        commission = self.calculate_commission(price, quantity)
        stamp_tax = abs(price * quantity * self.stamp_tax_rate) if quantity < 0 else 0.0
        return commission + stamp_tax

    def simulate_order(
        self,
        symbol: str,
        quantity: int,
        bar: pd.Series,
        execution_date: pd.Timestamp,
    ) -> ExecutionResult:
        """根据成交日K线模拟订单成交。"""
        if quantity == 0:
            return ExecutionResult(False, symbol, quantity, execution_date, reason="zero_quantity")

        if bool(bar.get("is_suspended", False)):
            return ExecutionResult(False, symbol, quantity, execution_date, reason="suspended")

        if self.execution_price_type not in bar:
            return ExecutionResult(False, symbol, quantity, execution_date, reason="missing_price_column")

        raw_price = pd.to_numeric(bar.get(self.execution_price_type), errors="coerce")
        if pd.isna(raw_price) or float(raw_price) <= 0:
            return ExecutionResult(False, symbol, quantity, execution_date, reason="invalid_price")

        # 保守处理：涨停无法买入，跌停无法卖出。
        if quantity > 0 and bool(bar.get("limit_up", False)):
            return ExecutionResult(False, symbol, quantity, execution_date, reason="limit_up")
        if quantity < 0 and bool(bar.get("limit_down", False)):
            return ExecutionResult(False, symbol, quantity, execution_date, reason="limit_down")

        raw_price = float(raw_price)
        if quantity > 0:
            execution_price = raw_price * (1 + self.slippage_rate)
        else:
            execution_price = raw_price * (1 - self.slippage_rate)

        trade_value = abs(execution_price * quantity)
        commission = self.calculate_commission(execution_price, quantity)
        stamp_tax = trade_value * self.stamp_tax_rate if quantity < 0 else 0.0
        slippage_cost = abs(raw_price * quantity) * self.slippage_rate
        total_fee = commission + stamp_tax + slippage_cost

        return ExecutionResult(
            success=True,
            symbol=symbol,
            quantity=quantity,
            date=pd.Timestamp(execution_date).normalize(),
            price=execution_price,
            raw_price=raw_price,
            commission=commission,
            stamp_tax=stamp_tax,
            slippage_cost=slippage_cost,
            total_fee=total_fee,
        )
