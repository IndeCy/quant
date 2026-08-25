"""统一本地 Paper Broker 适配层。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.paper_execution import BrokerConfig, BrokerSimulator, OrderManager, PaperOrder
from backtest.paper_trading import PaperTradingStore
from runtime.paper_broker_models import (
    PaperBrokerSyncResult,
    PaperBrokerTarget,
    RiskReductionPlanResult,
)
from runtime.paper_execution_policy import PaperExecutionPolicyManager
from runtime.paper_open_order_sizing import (
    OpenOrderResizeResult,
    PaperOpenOrderSizingService,
    ensure_paper_order_runtime_columns,
)


LOT_SIZE = 100

class LocalPaperBroker:
    """把策略目标权重转成统一模拟盘委托、成交和持仓。"""

    def __init__(self, db_path: str | Path, broker_config: BrokerConfig | None = None) -> None:
        self.store = PaperTradingStore(db_path)
        self.execution_policies = PaperExecutionPolicyManager(db_path, broker_config)
        self.broker = self.execution_policies.default_broker
        self.open_order_sizing = PaperOpenOrderSizingService(
            self.store,
            self.execution_policies,
        )
        ensure_paper_order_runtime_columns(self.store.conn)

    def close(self) -> None:
        """关闭底层模拟盘数据库。"""
        self.store.close()

    def sync_target(self, target: PaperBrokerTarget) -> PaperBrokerSyncResult:
        """同步最新目标并创建 T+1 委托；仅显式启用时兼容撮合旧单。"""
        trade_date = _compact_date(target.trade_date)
        trade_iso = _iso_date(trade_date)
        market = _normalize_market_data(target.market_data)
        dates = sorted(_compact_date(item) for item in target.trading_dates)
        next_trade_date = _next_trade_date(trade_date, dates)
        account_id = self._get_or_create_account(target, trade_iso)
        self.execution_policies.bind_account(account_id)
        if next_trade_date:
            self.open_order_sizing.save_target(
                account_id,
                trade_iso,
                _iso_date(next_trade_date),
                target.target_weights,
            )

        executed, rejected = (0, 0)
        if target.execute_due_orders:
            executed, rejected = self._execute_due_orders(account_id, trade_iso, market)
        cancelled = 0
        if next_trade_date and target.replace_pending_orders:
            cancelled = self._cancel_pending_orders(account_id, "RISK_POLICY_REPLAN")
        created = 0
        if next_trade_date and not self._has_pending_orders(account_id):
            created = self._create_next_orders(
                account_id,
                target,
                trade_date,
                _iso_date(next_trade_date),
                market,
                allow_replacement=target.replace_pending_orders,
            )
        self._record_snapshot(account_id, target, trade_date, market)
        pending = len(self.store.list_orders(account_id, status="PENDING"))
        return PaperBrokerSyncResult(
            account_id,
            trade_date,
            next_trade_date or "",
            created,
            executed,
            rejected,
            pending,
            cancelled,
        )

    def execute_due_orders(
        self,
        trade_date: str,
        market_data: pd.DataFrame,
        account_ids: list[int] | None = None,
    ) -> tuple[int, int]:
        """撮合指定账户的到期委托；不传账户时保持撮合全部账户。"""
        market = _normalize_market_data(market_data)
        if account_ids is None:
            return self._execute_due_orders(None, _iso_date(trade_date), market)
        executed = 0
        rejected = 0
        for account_id in sorted(set(account_ids)):
            account_executed, account_rejected = self._execute_due_orders(account_id, _iso_date(trade_date), market)
            executed += account_executed
            rejected += account_rejected
        return executed, rejected

    def resize_due_orders(
        self,
        account_id: int,
        trade_date: str,
        market_data: pd.DataFrame,
    ) -> OpenOrderResizeResult:
        """显式启用时按T+1开盘价格重建到期策略订单。"""
        market = _normalize_market_data(market_data)
        return self.open_order_sizing.resize_due_orders(
            account_id,
            _iso_date(trade_date),
            market,
        )

    def prepare_risk_reduction(
        self,
        account_id: int,
        trade_date: str,
        signal_date: str,
        target_exposure: float,
        market_data: pd.DataFrame,
    ) -> RiskReductionPlanResult:
        """取消当日原策略单，并按当前持仓等比例生成风险减仓卖单。"""
        if not 0 <= float(target_exposure) <= 1:
            raise ValueError("target_exposure must be between 0 and 1")
        trade_iso = _iso_date(trade_date)
        market = _normalize_market_data(market_data)
        cursor = self.store.conn.execute(
            """
            UPDATE paper_order
            SET status = 'CANCELLED', reject_reason = 'RISK_REDUCTION_OVERRIDE',
                modify_time = CURRENT_TIMESTAMP
            WHERE account_id = ? AND status = 'PENDING' AND order_date <= ?
            """,
            (account_id, trade_iso),
        )
        cancelled = max(int(cursor.rowcount), 0)
        positions = self.store.list_positions(account_id)
        account = self.store.get_account(account_id)
        valued_positions: list[tuple[dict[str, Any], float]] = []
        for position in positions:
            symbol = str(position["symbol"])
            market_row = _market_row(market, trade_iso, symbol)
            price = _valuation_price(market_row, float(position["avg_cost"]))
            valued_positions.append((position, price))
        position_value = sum(int(position["quantity"]) * price for position, price in valued_positions)
        total_value = float(account["cash"]) + position_value
        target_position_value = min(position_value, total_value * float(target_exposure))
        scale = target_position_value / position_value if position_value > 0 else 0.0
        created = 0
        for position, price in valued_positions:
            current_quantity = int(position["quantity"])
            target_quantity = _round_lot(int(current_quantity * scale))
            sell_quantity = _round_lot(current_quantity - target_quantity)
            if sell_quantity <= 0:
                continue
            self.store.record_pending_order(
                account_id=account_id,
                order_date=trade_iso,
                symbol=str(position["symbol"]),
                symbol_name=str(position["symbol_name"]),
                side="SELL",
                price=price,
                quantity=sell_quantity,
                note=f"risk_reduction signal={_iso_date(signal_date)}",
            )
            created += 1
        self.store.conn.commit()
        return RiskReductionPlanResult(account_id, float(target_exposure), cancelled, created)

    def _get_or_create_account(self, target: PaperBrokerTarget, start_date: str) -> int:
        row = self.store.conn.execute(
            "SELECT id FROM paper_account WHERE strategy_code = ? ORDER BY id LIMIT 1",
            (target.strategy_id,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        return self.store.create_account(
            strategy_name=target.strategy_name,
            strategy_code=target.strategy_id,
            initial_cash=target.initial_cash,
            benchmark_symbol=target.benchmark_symbol,
            benchmark_name=target.benchmark_name,
            start_date=start_date,
        )

    def _execute_due_orders(self, account_id: int | None, trade_iso: str, market: pd.DataFrame) -> tuple[int, int]:
        account_filter = "" if account_id is None else "account_id = ? AND"
        params: tuple[Any, ...] = (trade_iso,) if account_id is None else (account_id, trade_iso)
        rows = self.store.conn.execute(
            f"""
            SELECT * FROM paper_order
            WHERE {account_filter} status = 'PENDING' AND order_date <= ?
            ORDER BY account_id, CASE WHEN side = 'SELL' THEN 0 ELSE 1 END, id
            """,
            params,
        ).fetchall()
        executed = 0
        rejected = 0
        for row in rows:
            order = dict(row)
            market_row = _market_row(market, trade_iso, str(order["symbol"]))
            if market_row is None:
                self._mark_rejected(int(order["id"]), trade_iso, "MISSING_MARKET_DATA")
                rejected += 1
                continue
            manager = OrderManager()
            paper_order = manager.create_order(
                signal_date=str(order["note"]).split("signal=", 1)[-1] if "signal=" in str(order["note"]) else trade_iso,
                execute_date=trade_iso,
                symbol=str(order["symbol"]),
                side=str(order["side"]),
                quantity=int(order["quantity"]),
                signal_price=float(order["price"]),
            )
            filled = self.execution_policies.execute(
                int(order["account_id"]),
                paper_order,
                market_row,
                manager,
            )
            if filled.status == "REJECTED":
                self._mark_rejected(int(order["id"]), trade_iso, filled.reject_reason)
                rejected += 1
                continue
            quantity = _round_lot(int(filled.filled_quantity))
            if quantity <= 0:
                self._mark_rejected(int(order["id"]), trade_iso, "LOT_SIZE_NO_FILL")
                rejected += 1
                continue
            amount = quantity * float(filled.fill_price)
            execution = manager.execution_logs[-1]
            commission = float(execution.commission)
            stamp_tax = float(execution.stamp_tax)
            cash_amount = (
                amount + commission
                if str(order["side"]) == "BUY"
                else amount - commission - stamp_tax
            )
            settlement_reason = self._settlement_reject_reason(
                int(order["account_id"]),
                str(order["symbol"]),
                str(order["side"]),
                quantity,
                cash_amount,
            )
            if settlement_reason:
                self._mark_rejected(int(order["id"]), trade_iso, settlement_reason)
                rejected += 1
                continue
            self._apply_fill(int(order["account_id"]), str(order["symbol"]), str(order["symbol_name"]), str(order["side"]), quantity, cash_amount)
            self.store.conn.execute(
                """
                UPDATE paper_order SET
                    fill_date = ?, fill_price = ?, filled_quantity = ?, amount = ?,
                    commission = ?, stamp_tax = ?, execution_impact = ?, status = ?,
                    reject_reason = '', modify_time = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    trade_iso,
                    float(filled.fill_price),
                    quantity,
                    amount,
                    commission,
                    stamp_tax,
                    float(execution.execution_impact),
                    filled.status,
                    int(order["id"]),
                ),
            )
            executed += 1
        self.store.conn.commit()
        return executed, rejected

    def _create_next_orders(
        self,
        account_id: int,
        target: PaperBrokerTarget,
        signal_date: str,
        execute_iso: str,
        market: pd.DataFrame,
        allow_replacement: bool = False,
    ) -> int:
        if not allow_replacement and self._has_orders(account_id, execute_iso):
            return 0
        target_quantities = self._target_quantities(account_id, target.target_weights, signal_date, market)
        current_quantities = {str(row["symbol"]): int(row["quantity"]) for row in self.store.list_positions(account_id)}
        created = 0
        for symbol in sorted(set(target_quantities) | set(current_quantities)):
            delta = target_quantities.get(symbol, 0) - current_quantities.get(symbol, 0)
            if delta == 0:
                continue
            price_row = _market_row(market, _iso_date(signal_date), symbol)
            if price_row is None:
                continue
            side = "BUY" if delta > 0 else "SELL"
            self.store.record_pending_order(
                account_id=account_id,
                order_date=execute_iso,
                symbol=symbol,
                symbol_name=str(price_row.get("name") or symbol),
                side=side,
                price=float(price_row["close"]),
                quantity=abs(int(delta)),
                note=f"local_paper_broker signal={_iso_date(signal_date)}",
            )
            created += 1
        return created

    def _cancel_pending_orders(self, account_id: int, reason: str) -> int:
        """重算目标前只取消未成交委托，已成交和已拒绝记录保持不可变。"""
        cursor = self.store.conn.execute(
            """
            UPDATE paper_order
            SET status = 'CANCELLED', reject_reason = ?, modify_time = CURRENT_TIMESTAMP
            WHERE account_id = ? AND status = 'PENDING'
            """,
            (reason, account_id),
        )
        self.store.conn.commit()
        return max(int(cursor.rowcount), 0)

    def _target_quantities(
        self,
        account_id: int,
        target_weights: dict[str, float],
        signal_date: str,
        market: pd.DataFrame,
    ) -> dict[str, int]:
        prices = _prices_for_date(market, _iso_date(signal_date))
        total_value = self._account_total_value(account_id, prices)
        quantities: dict[str, int] = {}
        for symbol, weight in target_weights.items():
            price = prices.get(symbol)
            if price is None or price <= 0 or weight <= 0:
                continue
            quantities[symbol] = _round_lot(int(total_value * float(weight) / price))
        return quantities

    def _account_total_value(self, account_id: int, prices: dict[str, float]) -> float:
        account = self.store.get_account(account_id)
        total = float(account["cash"])
        for row in self.store.list_positions(account_id):
            total += int(row["quantity"]) * float(prices.get(str(row["symbol"]), row["avg_cost"]))
        return total

    def _record_snapshot(self, account_id: int, target: PaperBrokerTarget, trade_date: str, market: pd.DataFrame) -> None:
        prices = _prices_for_date(market, _iso_date(trade_date))
        account = self.store.get_account(account_id)
        position_value = sum(
            int(row["quantity"]) * float(prices.get(str(row["symbol"]), row["avg_cost"]))
            for row in self.store.list_positions(account_id)
        )
        total_value = float(account["cash"]) + position_value
        initial_cash = float(account["initial_cash"]) or 1.0
        self.store.record_daily_snapshot(
            account_id=account_id,
            trade_date=_iso_date(trade_date),
            total_value=total_value,
            cash=float(account["cash"]),
            position_value=position_value,
            strategy_return=total_value / initial_cash - 1.0,
            benchmark_return=0.0,
            excess_return=total_value / initial_cash - 1.0,
            strongest_chain="",
            rebalance_signal="TARGET_SYNC",
            target_symbols=sorted(target.target_weights),
        )

    def _apply_fill(self, account_id: int, symbol: str, name: str, side: str, quantity: int, amount: float) -> None:
        if side == "BUY":
            self.store._apply_buy(account_id, symbol, name, quantity, amount)  # noqa: SLF001 - 复用现有持仓入账逻辑。
        else:
            self.store._apply_sell(account_id, symbol, quantity, amount)  # noqa: SLF001 - 复用现有持仓出账逻辑。

    def _settlement_reject_reason(
        self,
        account_id: int,
        symbol: str,
        side: str,
        quantity: int,
        amount: float,
    ) -> str:
        """在持仓入账前检查资金和可卖数量，业务拒单不得中断整个批次。"""
        if side == "BUY":
            account = self.store.get_account(account_id)
            return "INSUFFICIENT_CASH" if float(account["cash"]) + 1e-9 < amount else ""
        position = self.store.conn.execute(
            "SELECT quantity FROM paper_position WHERE account_id = ? AND symbol = ?",
            (account_id, symbol),
        ).fetchone()
        if position is None or int(position["quantity"]) < quantity:
            return "INSUFFICIENT_POSITION"
        return ""

    def _mark_rejected(self, order_id: int, trade_iso: str, reason: str) -> None:
        self.store.conn.execute(
            """
            UPDATE paper_order
            SET fill_date = ?, status = 'REJECTED', reject_reason = ?, modify_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (trade_iso, reason, order_id),
        )

    def _has_orders(self, account_id: int, execute_iso: str) -> bool:
        row = self.store.conn.execute(
            "SELECT 1 FROM paper_order WHERE account_id = ? AND order_date = ? LIMIT 1",
            (account_id, execute_iso),
        ).fetchone()
        return row is not None

    def _has_pending_orders(self, account_id: int) -> bool:
        """未完成委托存在时不得叠加下一批目标单，避免跨日重复下单。"""
        row = self.store.conn.execute(
            "SELECT 1 FROM paper_order WHERE account_id = ? AND status = 'PENDING' LIMIT 1",
            (account_id,),
        ).fetchone()
        return row is not None

def _normalize_market_data(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "trade_date" not in data.columns and "date" in data.columns:
        data["trade_date"] = data["date"]
    if "symbol" not in data.columns and "ts_code" in data.columns:
        data["symbol"] = data["ts_code"]
    if "volume" not in data.columns and "vol" in data.columns:
        data["volume"] = data["vol"]
    data["trade_date"] = data["trade_date"].map(lambda value: _iso_date(str(value)))
    for column in ["is_suspended", "limit_up", "limit_down"]:
        if column not in data.columns:
            data[column] = False
    return data.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _market_row(data: pd.DataFrame, trade_iso: str, symbol: str) -> pd.Series | None:
    rows = data[(data["trade_date"] == trade_iso) & (data["symbol"] == symbol)]
    return None if rows.empty else rows.iloc[-1]


def _prices_for_date(data: pd.DataFrame, trade_iso: str) -> dict[str, float]:
    rows = data[data["trade_date"] == trade_iso]
    return {str(row["symbol"]): float(row["close"]) for _, row in rows.iterrows() if math.isfinite(float(row["close"]))}


def _valuation_price(market_row: pd.Series | None, fallback: float) -> float:
    """风险计划优先使用开盘价估值，行情缺失时回退持仓成本等待成交层拒单。"""
    if market_row is not None:
        for column in ["open", "close"]:
            value = float(market_row.get(column, 0.0) or 0.0)
            if math.isfinite(value) and value > 0:
                return value
    return max(float(fallback), 0.0)


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text


def _iso_date(value: str) -> str:
    text = _compact_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _next_trade_date(trade_date: str, trading_dates: list[str]) -> str:
    for item in sorted(trading_dates):
        if item > trade_date:
            return item
    return ""


def _round_lot(quantity: int) -> int:
    return max(int(quantity) // LOT_SIZE, 0) * LOT_SIZE
