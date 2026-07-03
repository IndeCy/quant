"""统一账户与组合视图。"""

from __future__ import annotations

from typing import Any


def build_account_snapshot(
    strategy_id: str,
    trade_date: str,
    total_value: float,
    cash: float,
    target_weights: dict[str, float],
    actual_positions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """构建包含目标、实际、漂移和调仓差异的账户快照。"""
    total = float(total_value)
    if total <= 0:
        raise ValueError("total_value must be positive")
    cash_value = float(cash)
    symbols = sorted(set(target_weights) | set(actual_positions))
    positions = []
    for symbol in symbols:
        actual = actual_positions.get(symbol, {})
        actual_amount = float(actual.get("market_value", 0.0))
        target_weight = float(target_weights.get(symbol, 0.0))
        target_amount = target_weight * total
        actual_weight = actual_amount / total
        trade_amount = target_amount - actual_amount
        positions.append(
            {
                "symbol": symbol,
                "target_weight": target_weight,
                "actual_weight": actual_weight,
                "drift_weight": actual_weight - target_weight,
                "target_amount": target_amount,
                "actual_amount": actual_amount,
                "trade_amount": trade_amount,
                "action": _action(trade_amount),
                "quantity": int(actual.get("quantity", 0) or 0),
                "last_close": float(actual.get("last_close", 0.0) or 0.0),
            }
        )
    max_abs_drift = max((abs(item["drift_weight"]) for item in positions), default=0.0)
    return {
        "strategy_id": strategy_id,
        "trade_date": trade_date,
        "total_value": total,
        "cash": cash_value,
        "cash_weight": cash_value / total,
        "position_value": sum(item["actual_amount"] for item in positions),
        "target_position_weight": sum(float(value) for value in target_weights.values()),
        "max_abs_drift": max_abs_drift,
        "positions": positions,
    }


def _action(trade_amount: float) -> str:
    """把调仓金额转成操作方向。"""
    if trade_amount > 1e-6:
        return "BUY"
    if trade_amount < -1e-6:
        return "SELL"
    return "HOLD"
