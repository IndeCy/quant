"""股票与场内基金共用 M0、按资产类别区分印花税的执行适配器。"""

from __future__ import annotations

import pandas as pd

from backtest.execution_model import ExecutionModel, ExecutionResult


class MixedAssetExecutionModel(ExecutionModel):
    """所有订单仍由 M0 成交模型执行，ETF 卖出印花税固定为零。"""

    def __init__(
        self,
        fund_symbols: set[str],
        *,
        commission_rate: float = 0.0003,
        stock_stamp_tax_rate: float = 0.001,
        slippage_bps: float = 5.0,
        min_commission: float = 5.0,
    ) -> None:
        super().__init__(
            commission_rate=commission_rate,
            stamp_tax_rate=stock_stamp_tax_rate,
            slippage_bps=slippage_bps,
            min_commission=min_commission,
        )
        self.fund_symbols = frozenset(str(item) for item in fund_symbols)
        self._fund_model = ExecutionModel(
            commission_rate=commission_rate,
            stamp_tax_rate=0.0,
            slippage_bps=slippage_bps,
            min_commission=min_commission,
        )

    def simulate_order(
        self,
        symbol: str,
        quantity: int,
        bar: pd.Series,
        execution_date: pd.Timestamp,
    ) -> ExecutionResult:
        """按代码选择股票或ETF税费模型，成交语义保持 M0。"""
        model = self._fund_model if str(symbol) in self.fund_symbols else self
        if model is self:
            return super().simulate_order(symbol, quantity, bar, execution_date)
        return model.simulate_order(symbol, quantity, bar, execution_date)
