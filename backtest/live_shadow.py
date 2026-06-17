"""
Small Capital Shadow Live System。

该模块用于每日收盘后准实盘流程编排：更新数据、生成信号、生成目标组合、
生成调仓计划、检查市场约束、控制漂移并输出每日对账。模块不接券商接口，
也不修改 M0 回测执行层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class CapitalConstraintResult:
    """资金约束应用结果。"""

    target_weights: dict[str, float]
    target_amounts: dict[str, float]
    cash_weight: float


@dataclass(frozen=True)
class RebalancePlan:
    """每日调仓计划。"""

    target_weights: dict[str, float]
    target_amounts: dict[str, float]
    trade_amounts: dict[str, float]
    total_buy_amount: float
    total_sell_amount: float


@dataclass(frozen=True)
class MarketConstraintResult:
    """单标的市场约束检查结果。"""

    symbol: str
    status: str
    reasons: list[str] = field(default_factory=list)
    allowed_amount: float = 0.0
    requested_amount: float = 0.0
    t1_confirmation_required: bool = True


@dataclass(frozen=True)
class DriftResult:
    """组合漂移分析结果。"""

    drift_by_symbol: dict[str, float]
    max_abs_drift: float
    should_rebalance: bool
    rebalance_symbols: list[str]


@dataclass(frozen=True)
class DailyReconciliationResult:
    """每日准实盘对账结果。"""

    paper_pnl: float
    theoretical_pnl: float
    execution_pnl: float
    deviation_breakdown: dict[str, float]


@dataclass(frozen=True)
class DailyLiveResult:
    """每日 live loop 输出。"""

    trade_date: str
    signal: dict[str, float]
    target_weights: dict[str, float]
    rebalance_plan: RebalancePlan
    constraint_checks: dict[str, MarketConstraintResult]
    drift: DriftResult


class CapitalConstraint:
    """固定资金规模、单票上限和现金比例约束。"""

    def __init__(self, capital: float, max_symbol_weight: float = 0.20, min_cash_ratio: float = 0.05) -> None:
        if capital <= 0:
            raise ValueError("capital 必须大于0")
        if not 0 <= max_symbol_weight <= 1:
            raise ValueError("max_symbol_weight 必须在 0 到 1 之间")
        if not 0 <= min_cash_ratio <= 1:
            raise ValueError("min_cash_ratio 必须在 0 到 1 之间")
        self.capital = float(capital)
        self.max_symbol_weight = float(max_symbol_weight)
        self.min_cash_ratio = float(min_cash_ratio)

    def apply(self, target_weights: dict[str, float]) -> CapitalConstraintResult:
        """应用资金约束，保留最低现金比例。"""
        investable = max(1.0 - self.min_cash_ratio, 0.0)
        capped = {
            symbol: min(max(float(weight), 0.0), self.max_symbol_weight)
            for symbol, weight in target_weights.items()
        }
        total = sum(capped.values())
        if total > investable and total > 0:
            scale = investable / total
            capped = {symbol: weight * scale for symbol, weight in capped.items()}
        target_amounts = {symbol: weight * self.capital for symbol, weight in capped.items()}
        cash_weight = max(1.0 - sum(capped.values()), 0.0)
        return CapitalConstraintResult(capped, target_amounts, cash_weight)


class MarketConstraintChecker:
    """真实市场约束检查器。"""

    def __init__(self, max_amount_participation: float = 0.10) -> None:
        self.max_amount_participation = float(max_amount_participation)

    def check_plan(
        self,
        trade_amounts: dict[str, float],
        market_data: pd.DataFrame,
        side_by_symbol: dict[str, str],
    ) -> dict[str, MarketConstraintResult]:
        """检查调仓计划是否受涨跌停、停牌、流动性和 T+1 限制影响。"""
        frame = market_data.copy()
        result: dict[str, MarketConstraintResult] = {}
        for symbol, requested_amount in trade_amounts.items():
            row = self._row(frame, symbol)
            reasons: list[str] = []
            side = side_by_symbol.get(symbol, "BUY")
            if bool(row.get("is_suspended", False)):
                reasons.append("SUSPENDED_NO_FILL")
            open_price = float(row.get("open", row.get("close", 0.0)) or 0.0)
            if side == "BUY" and open_price >= float(row.get("limit_up", float("inf"))):
                reasons.append("LIMIT_UP_NO_FILL")
            if side == "SELL" and open_price <= float(row.get("limit_down", float("-inf"))):
                reasons.append("LIMIT_DOWN_NO_FILL")
            allowed_amount = float(row.get("amount", 0.0)) * self.max_amount_participation
            if abs(float(requested_amount)) > allowed_amount:
                reasons.append("LIQUIDITY_LIMIT")
            status = "BLOCKED" if any(reason != "LIQUIDITY_LIMIT" for reason in reasons) else "WARN"
            if not reasons:
                status = "OK"
            result[symbol] = MarketConstraintResult(
                symbol=symbol,
                status=status,
                reasons=reasons,
                allowed_amount=allowed_amount,
                requested_amount=float(requested_amount),
                t1_confirmation_required=True,
            )
        return result

    def _row(self, frame: pd.DataFrame, symbol: str) -> pd.Series:
        rows = frame[frame["symbol"] == symbol]
        if rows.empty:
            raise ValueError(f"缺少市场数据: {symbol}")
        return rows.iloc[0]


class PortfolioDriftSystem:
    """目标组合与实际组合漂移控制。"""

    def __init__(self, threshold: float = 0.05) -> None:
        self.threshold = float(threshold)

    def analyze(self, target_weights: dict[str, float], actual_weights: dict[str, float]) -> DriftResult:
        """计算组合漂移，并判断是否触发调仓提示。"""
        symbols = sorted(set(target_weights) | set(actual_weights))
        drift = {
            symbol: float(actual_weights.get(symbol, 0.0)) - float(target_weights.get(symbol, 0.0))
            for symbol in symbols
        }
        rebalance_symbols = [symbol for symbol, value in drift.items() if abs(value) > self.threshold]
        max_abs_drift = max((abs(value) for value in drift.values()), default=0.0)
        return DriftResult(
            drift_by_symbol=drift,
            max_abs_drift=max_abs_drift,
            should_rebalance=bool(rebalance_symbols),
            rebalance_symbols=rebalance_symbols,
        )


class DailyReconciliation:
    """每日 paper/theoretical/execution 对账。"""

    def reconcile(
        self,
        previous_value: float,
        paper_value: float,
        theoretical_value: float,
        execution_cost: float,
        drift_cost: float,
    ) -> DailyReconciliationResult:
        """输出 PnL 和偏离拆解。"""
        paper_pnl = float(paper_value) - float(previous_value)
        theoretical_pnl = float(theoretical_value) - float(previous_value)
        execution_pnl = -float(execution_cost)
        total_deviation = paper_pnl - theoretical_pnl
        breakdown = {
            "total_deviation": total_deviation,
            "execution_cost": float(execution_cost),
            "drift_cost": float(drift_cost),
            "unexplained": total_deviation + float(execution_cost) + float(drift_cost),
        }
        return DailyReconciliationResult(paper_pnl, theoretical_pnl, execution_pnl, breakdown)


class LiveDataLoop:
    """每日收盘后的准实盘主循环。"""

    def __init__(
        self,
        data_updater: Callable[[str], pd.DataFrame],
        signal_generator: Callable[[pd.DataFrame], dict[str, float]],
        portfolio_builder: Callable[[dict[str, float]], dict[str, float]],
        capital_constraint: CapitalConstraint,
        constraint_checker: MarketConstraintChecker | None = None,
        drift_system: PortfolioDriftSystem | None = None,
    ) -> None:
        self.data_updater = data_updater
        self.signal_generator = signal_generator
        self.portfolio_builder = portfolio_builder
        self.capital_constraint = capital_constraint
        self.constraint_checker = constraint_checker or MarketConstraintChecker()
        self.drift_system = drift_system or PortfolioDriftSystem()

    def run_daily(self, trade_date: str, actual_weights: dict[str, float] | None = None) -> DailyLiveResult:
        """执行每日数据更新、信号、目标组合、调仓计划和约束检查。"""
        actual_weights = actual_weights or {}
        market_data = self.data_updater(trade_date)
        signal = self.signal_generator(market_data)
        raw_target = self.portfolio_builder(signal)
        constrained = self.capital_constraint.apply(raw_target)
        plan = self._rebalance_plan(constrained, actual_weights)
        side_by_symbol = {
            symbol: "BUY" if amount > 0 else "SELL"
            for symbol, amount in plan.trade_amounts.items()
            if amount != 0
        }
        checks = self.constraint_checker.check_plan(plan.trade_amounts, market_data, side_by_symbol)
        drift = self.drift_system.analyze(constrained.target_weights, actual_weights)
        return DailyLiveResult(
            trade_date=trade_date,
            signal=signal,
            target_weights=constrained.target_weights,
            rebalance_plan=plan,
            constraint_checks=checks,
            drift=drift,
        )

    def _rebalance_plan(
        self,
        constrained: CapitalConstraintResult,
        actual_weights: dict[str, float],
    ) -> RebalancePlan:
        """根据目标权重和实际权重生成金额调仓计划。"""
        symbols = sorted(set(constrained.target_weights) | set(actual_weights))
        trade_amounts = {
            symbol: (constrained.target_weights.get(symbol, 0.0) - actual_weights.get(symbol, 0.0))
            * self.capital_constraint.capital
            for symbol in symbols
        }
        return RebalancePlan(
            target_weights=constrained.target_weights,
            target_amounts=constrained.target_amounts,
            trade_amounts=trade_amounts,
            total_buy_amount=sum(amount for amount in trade_amounts.values() if amount > 0),
            total_sell_amount=abs(sum(amount for amount in trade_amounts.values() if amount < 0)),
        )
