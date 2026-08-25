"""
Paper Trading / Shadow Trading 执行仿真层。

该模块用于验证策略目标权重在真实交易约束下是否仍可执行，不修改
M0 ExecutionModel，也不改变因子或策略逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import pandas as pd

from backtest.paper_drift import DriftAnalyzer


@dataclass
class BrokerConfig:
    """模拟券商成交参数。"""

    slippage_bps: float = 5.0
    execution_delay: int = 1
    max_participation_rate: float = 0.20
    commission_rate: float = 0.0
    stamp_tax_rate: float = 0.0
    min_commission: float = 0.0
    lot_size: int = 1
    open_aware_order_sizing: bool = False
    tax_exempt_symbols: frozenset[str] = field(default_factory=frozenset)


@dataclass
class PaperOrder:
    """模拟盘委托单。"""

    order_id: int
    signal_date: str
    execute_date: str
    symbol: str
    side: str
    quantity: int
    signal_price: float
    status: str = "PENDING"
    filled_quantity: int = 0
    fill_price: float = 0.0
    reject_reason: str = ""


@dataclass
class ExecutionLog:
    """成交或拒单日志。"""

    order_id: int
    symbol: str
    side: str
    status: str
    quantity: int
    fill_price: float
    execution_impact: float
    reason: str = ""
    commission: float = 0.0
    stamp_tax: float = 0.0


@dataclass
class PortfolioSnapshot:
    """模拟盘每日组合快照。"""

    date: str
    cash: float
    total_value: float
    actual_holdings: dict[str, int]
    target_holdings: dict[str, int]
    drift: dict[str, int]
    unrealized_pnl: dict[str, float]


@dataclass
class PaperTradingResult:
    """模拟盘运行结果。"""

    orders: list[PaperOrder]
    executions: list[ExecutionLog]
    snapshots: list[PortfolioSnapshot]
    actual_turnover: float
    total_execution_cost: float = 0.0


class OrderManager:
    """管理委托生命周期和执行日志。"""

    def __init__(self) -> None:
        self.orders: list[PaperOrder] = []
        self.execution_logs: list[ExecutionLog] = []
        self._next_order_id = 1

    def create_order(
        self,
        signal_date: str,
        execute_date: str,
        symbol: str,
        side: str,
        quantity: int,
        signal_price: float,
    ) -> PaperOrder:
        """创建待执行委托单。"""
        order = PaperOrder(
            order_id=self._next_order_id,
            signal_date=signal_date,
            execute_date=execute_date,
            symbol=symbol,
            side=side,
            quantity=int(quantity),
            signal_price=float(signal_price),
        )
        self._next_order_id += 1
        self.orders.append(order)
        return order

    def mark_filled(
        self,
        order_id: int,
        filled_quantity: int,
        fill_price: float,
        *,
        commission: float = 0.0,
        stamp_tax: float = 0.0,
    ) -> PaperOrder:
        """按成交数量更新委托状态。"""
        order = self._find(order_id)
        order.filled_quantity = int(filled_quantity)
        order.fill_price = float(fill_price)
        order.status = "FILLED" if filled_quantity >= order.quantity else "PARTIAL_FILLED"
        impact = abs(order.fill_price - order.signal_price) * order.filled_quantity
        self.execution_logs.append(
            ExecutionLog(
                order_id=order_id,
                symbol=order.symbol,
                side=order.side,
                status=order.status,
                quantity=order.filled_quantity,
                fill_price=order.fill_price,
                execution_impact=impact,
                commission=float(commission),
                stamp_tax=float(stamp_tax),
            )
        )
        return order

    def mark_rejected(self, order_id: int, reason: str) -> PaperOrder:
        """拒绝委托并记录原因。"""
        order = self._find(order_id)
        order.status = "REJECTED"
        order.reject_reason = reason
        self.execution_logs.append(
            ExecutionLog(order_id, order.symbol, order.side, "REJECTED", 0, 0.0, 0.0, reason)
        )
        return order

    def _find(self, order_id: int) -> PaperOrder:
        for order in self.orders:
            if order.order_id == order_id:
                return order
        raise ValueError(f"委托不存在: {order_id}")


class BrokerSimulator:
    """模拟券商成交限制。"""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()

    def execute(
        self,
        order: PaperOrder,
        market_row: pd.Series,
        manager: OrderManager,
        *,
        cash_available: float | None = None,
    ) -> PaperOrder:
        """按行情约束执行一笔委托。"""
        reason = self._reject_reason(order, market_row)
        if reason:
            return manager.mark_rejected(order.order_id, reason)

        open_price = float(market_row["open"])
        volume = int(market_row.get("volume", 0))
        max_quantity = max(int(volume * self.config.max_participation_rate), 0)
        lot_size = max(int(self.config.lot_size), 1)
        filled_quantity = min(order.quantity, max_quantity)
        filled_quantity = (filled_quantity // lot_size) * lot_size
        direction = 1 if order.side == "BUY" else -1
        fill_price = open_price * (1 + direction * self.config.slippage_bps / 10_000)
        if order.side == "BUY" and cash_available is not None:
            filled_quantity = min(
                filled_quantity,
                self._affordable_quantity(float(cash_available), fill_price),
            )
        if filled_quantity <= 0:
            reason = "CASH_NO_FILL" if order.side == "BUY" else "LIQUIDITY_NO_FILL"
            return manager.mark_rejected(order.order_id, reason)

        notional = fill_price * filled_quantity
        commission = max(
            notional * self.config.commission_rate,
            self.config.min_commission,
        )
        stamp_tax = 0.0
        if (
            order.side == "SELL"
            and order.symbol not in self.config.tax_exempt_symbols
        ):
            stamp_tax = notional * self.config.stamp_tax_rate
        filled_order = manager.mark_filled(
            order.order_id,
            filled_quantity,
            fill_price,
            commission=commission,
            stamp_tax=stamp_tax,
        )
        last_log = manager.execution_logs[-1]
        last_log.execution_impact = abs(fill_price - open_price) * filled_quantity
        return filled_order

    def _affordable_quantity(self, cash: float, fill_price: float) -> int:
        """按佣金和整手约束计算最大可买数量。"""
        lot_size = max(int(self.config.lot_size), 1)
        available = max(cash - self.config.min_commission, 0.0)
        unit_cash = fill_price * (1 + self.config.commission_rate)
        quantity = int(available / unit_cash) if unit_cash > 0 else 0
        quantity = (quantity // lot_size) * lot_size
        while quantity > 0:
            notional = fill_price * quantity
            commission = max(
                notional * self.config.commission_rate,
                self.config.min_commission,
            )
            if notional + commission <= cash:
                return quantity
            quantity -= lot_size
        return 0

    def _reject_reason(self, order: PaperOrder, market_row: pd.Series) -> str:
        """判断停牌、缺价和涨跌停导致的不可成交。"""
        if bool(market_row.get("is_suspended", False)):
            return "SUSPENDED_NO_FILL"
        open_price = float(market_row.get("open", 0.0) or 0.0)
        if not math.isfinite(open_price) or open_price <= 0:
            return "INVALID_PRICE_NO_FILL"
        if order.side == "BUY" and bool(market_row.get("limit_up", False)):
            return "LIMIT_UP_NO_FILL"
        if order.side == "SELL" and bool(market_row.get("limit_down", False)):
            return "LIMIT_DOWN_NO_FILL"
        return ""


class PortfolioTracker:
    """跟踪模拟盘实际持仓、目标持仓、漂移和浮动盈亏。"""

    def __init__(self, initial_cash: float) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.actual_holdings: dict[str, int] = {}
        self.target_holdings: dict[str, int] = {}
        self.avg_cost: dict[str, float] = {}
        self.traded_notional = 0.0
        self.total_fees = 0.0

    def set_target_holdings(self, target_holdings: dict[str, int]) -> None:
        """设置当前信号对应的目标持仓。"""
        self.target_holdings = {symbol: int(quantity) for symbol, quantity in target_holdings.items()}

    def apply_fill(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        signal_price: float,
        *,
        commission: float = 0.0,
        stamp_tax: float = 0.0,
    ) -> None:
        """成交后更新现金、持仓和成本。"""
        quantity = int(quantity)
        price = float(price)
        if quantity <= 0:
            return
        old_quantity = self.actual_holdings.get(symbol, 0)
        if side == "BUY":
            new_quantity = old_quantity + quantity
            old_cost = self.avg_cost.get(symbol, float(signal_price)) * old_quantity
            self.avg_cost[symbol] = (old_cost + price * quantity) / new_quantity
            self.actual_holdings[symbol] = new_quantity
            self.cash -= price * quantity + commission
        else:
            sold_quantity = min(quantity, old_quantity)
            self.actual_holdings[symbol] = old_quantity - sold_quantity
            self.cash += price * sold_quantity - commission - stamp_tax
            if self.actual_holdings[symbol] <= 0:
                self.actual_holdings.pop(symbol, None)
                self.avg_cost.pop(symbol, None)
        self.traded_notional += price * quantity
        self.total_fees += float(commission) + float(stamp_tax)

    def snapshot(self, date: str, prices: dict[str, float]) -> PortfolioSnapshot:
        """生成组合快照。"""
        symbols = set(self.actual_holdings) | set(self.target_holdings)
        drift = {
            symbol: self.actual_holdings.get(symbol, 0) - self.target_holdings.get(symbol, 0)
            for symbol in symbols
        }
        unrealized = {
            symbol: self.actual_holdings.get(symbol, 0)
            * (float(prices.get(symbol, self.avg_cost.get(symbol, 0.0))) - self.avg_cost.get(symbol, 0.0))
            for symbol in symbols
        }
        position_value = sum(self.actual_holdings.get(symbol, 0) * float(prices.get(symbol, 0.0)) for symbol in symbols)
        return PortfolioSnapshot(
            date=date,
            cash=self.cash,
            total_value=self.cash + position_value,
            actual_holdings=dict(self.actual_holdings),
            target_holdings=dict(self.target_holdings),
            drift=drift,
            unrealized_pnl=unrealized,
        )


class PaperTradingEngine:
    """从信号到订单、成交和组合更新的模拟盘引擎。"""

    def __init__(
        self,
        initial_cash: float,
        broker: BrokerSimulator | None = None,
        order_manager: OrderManager | None = None,
        portfolio_tracker: PortfolioTracker | None = None,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.broker = broker or BrokerSimulator()
        self.order_manager = order_manager or OrderManager()
        self.portfolio = portfolio_tracker or PortfolioTracker(initial_cash)

    def run_signals(self, signals_by_date: dict[str, dict[str, float]], market_data: pd.DataFrame) -> PaperTradingResult:
        """执行 signal→order→execution→portfolio update 流程。"""
        if self.broker.config.open_aware_order_sizing:
            from backtest.paper_open_aware_replay import run_open_aware_replay

            return run_open_aware_replay(self, signals_by_date, market_data)
        data = self._normalize_market_data(market_data)
        trading_dates = sorted(data["date"].unique())
        market_by_date = {
            date: rows.set_index("symbol", drop=False)
            for date, rows in data.groupby("date", sort=False)
        }
        signals = {
            pd.Timestamp(date).strftime("%Y-%m-%d"): weights
            for date, weights in signals_by_date.items()
        }
        pending: dict[str, list[PaperOrder]] = {}
        latest_prices: dict[str, float] = {}
        snapshots: list[PortfolioSnapshot] = []
        for date in trading_dates:
            daily_market = market_by_date[date]
            for order in pending.pop(date, []):
                market_row = self._market_row(daily_market, order.symbol)
                filled = self.broker.execute(
                    order,
                    market_row,
                    self.order_manager,
                    cash_available=self.portfolio.cash,
                )
                if filled.status in {"FILLED", "PARTIAL_FILLED"}:
                    log = self.order_manager.execution_logs[-1]
                    self.portfolio.apply_fill(
                        filled.symbol,
                        filled.side,
                        filled.filled_quantity,
                        filled.fill_price,
                        filled.signal_price,
                        commission=log.commission,
                        stamp_tax=log.stamp_tax,
                    )
            latest_prices.update(
                {
                    str(row["symbol"]): float(row["close"])
                    for _, row in daily_market.iterrows()
                    if pd.notna(row["close"]) and float(row["close"]) > 0
                }
            )
            if date in signals:
                portfolio_value = self.portfolio.snapshot(
                    date,
                    latest_prices,
                ).total_value
                target_holdings = self._target_holdings(
                    signals[date],
                    latest_prices,
                    portfolio_value,
                )
                self.portfolio.set_target_holdings(target_holdings)
                execute_date = self._execution_date(date, trading_dates)
                if execute_date is not None:
                    pending.setdefault(execute_date, []).extend(
                        self._create_rebalance_orders(
                            date,
                            execute_date,
                            target_holdings,
                            latest_prices,
                        )
                    )
            snapshots.append(self.portfolio.snapshot(date, latest_prices))
        actual_turnover = self.portfolio.traded_notional / self.initial_cash if self.initial_cash else 0.0
        total_cost = self.portfolio.total_fees + sum(
            log.execution_impact
            for log in self.order_manager.execution_logs
            if log.status != "REJECTED"
        )
        return PaperTradingResult(
            orders=self.order_manager.orders,
            executions=self.order_manager.execution_logs,
            snapshots=snapshots,
            actual_turnover=actual_turnover,
            total_execution_cost=total_cost,
        )

    def _normalize_market_data(self, market_data: pd.DataFrame) -> pd.DataFrame:
        frame = market_data.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        return frame.sort_values(["date", "symbol"]).reset_index(drop=True)

    def _execution_date(self, signal_date: str, trading_dates: list[str]) -> str | None:
        signal = pd.to_datetime(signal_date).strftime("%Y-%m-%d")
        future_dates = [date for date in trading_dates if date > signal]
        index = self.broker.config.execution_delay - 1
        return future_dates[index] if len(future_dates) > index else None

    def _target_holdings(
        self,
        signals: dict[str, float],
        prices: dict[str, float],
        portfolio_value: float,
    ) -> dict[str, int]:
        target: dict[str, int] = {}
        lot_size = max(int(self.broker.config.lot_size), 1)
        for symbol, weight in signals.items():
            price = float(prices.get(symbol, 0.0))
            if price <= 0:
                continue
            quantity = int(portfolio_value * float(weight) / price)
            target[symbol] = (quantity // lot_size) * lot_size
        return target

    def _create_rebalance_orders(
        self,
        signal_date: str,
        execute_date: str,
        target_holdings: dict[str, int],
        prices: dict[str, float],
    ) -> list[PaperOrder]:
        orders: list[PaperOrder] = []
        symbols = set(target_holdings) | set(self.portfolio.actual_holdings)
        for symbol in sorted(symbols):
            target_quantity = target_holdings.get(symbol, 0)
            actual_quantity = self.portfolio.actual_holdings.get(symbol, 0)
            delta = target_quantity - actual_quantity
            if delta == 0:
                continue
            side = "BUY" if delta > 0 else "SELL"
            signal_price = float(prices.get(symbol, 0.0))
            if signal_price <= 0:
                continue
            orders.append(
                self.order_manager.create_order(signal_date, execute_date, symbol, side, abs(delta), signal_price)
            )
        return sorted(orders, key=lambda order: (order.side == "BUY", order.symbol))

    def _market_row(
        self,
        daily_market: pd.DataFrame,
        symbol: str,
    ) -> pd.Series:
        if symbol not in daily_market.index:
            return pd.Series(
                {
                    "open": 0.0,
                    "close": 0.0,
                    "volume": 0,
                    "is_suspended": True,
                    "limit_up": False,
                    "limit_down": False,
                }
            )
        row = daily_market.loc[symbol]
        return row.iloc[0] if isinstance(row, pd.DataFrame) else row
