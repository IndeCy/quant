"""本地Paper Broker的输入输出契约。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PaperBrokerTarget:
    """策略盘后目标组合，统一进入本地模拟券商。"""

    strategy_id: str
    strategy_name: str
    trade_date: str
    target_weights: dict[str, float]
    market_data: pd.DataFrame
    trading_dates: list[str]
    initial_cash: float = 1_000_000.0
    benchmark_symbol: str = "510300"
    benchmark_name: str = "沪深300"
    execute_due_orders: bool = False
    replace_pending_orders: bool = False


@dataclass(frozen=True)
class PaperBrokerSyncResult:
    """本地模拟券商同步结果。"""

    account_id: int
    trade_date: str
    next_trade_date: str
    created_orders: int
    executed_orders: int
    rejected_orders: int
    pending_orders: int
    cancelled_orders: int = 0


@dataclass(frozen=True)
class RiskReductionPlanResult:
    """风险减仓覆盖原委托后的订单计划结果。"""

    account_id: int
    target_exposure: float
    cancelled_orders: int
    created_orders: int
