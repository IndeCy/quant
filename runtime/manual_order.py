"""人工调仓单领域逻辑。"""

from __future__ import annotations

from typing import Any


ORDER_DRAFT_STATUS = "DRAFT"
ORDER_CONFIRMED_STATUS = "CONFIRMED"
ORDER_FILLED_STATUS = "FILLED"
ORDER_REJECTED_STATUS = "REJECTED"
ORDER_CANCELLED_STATUS = "CANCELLED"


def build_order_draft_from_snapshot(snapshot: dict[str, Any], min_trade_amount: float = 100.0) -> dict[str, Any]:
    """把账户快照中的目标/实际差异转换为手工调仓草案。"""
    strategy_id = str(snapshot["strategy_id"])
    trade_date = str(snapshot["trade_date"])
    threshold = abs(float(min_trade_amount))
    orders = []
    for item in snapshot.get("positions", []):
        trade_amount = float(item.get("trade_amount", 0.0))
        if abs(trade_amount) < threshold:
            continue
        side = "BUY" if trade_amount > 0 else "SELL"
        suggested_price = float(item.get("last_close", 0.0) or 0.0)
        suggested_quantity = _suggest_quantity(abs(trade_amount), suggested_price)
        orders.append(
            {
                "strategy_id": strategy_id,
                "trade_date": trade_date,
                "symbol": str(item["symbol"]),
                "side": side,
                "status": ORDER_DRAFT_STATUS,
                "target_weight": float(item.get("target_weight", 0.0)),
                "actual_weight": float(item.get("actual_weight", 0.0)),
                "drift_weight": float(item.get("drift_weight", 0.0)),
                "target_amount": float(item.get("target_amount", 0.0)),
                "actual_amount": float(item.get("actual_amount", 0.0)),
                "trade_amount": trade_amount,
                "suggested_quantity": suggested_quantity,
                "suggested_price": suggested_price,
                "filled_quantity": 0,
                "filled_price": 0.0,
                "reject_reason": "",
            }
        )
    return {
        "strategy_id": strategy_id,
        "trade_date": trade_date,
        "status": ORDER_DRAFT_STATUS,
        "source": "account_snapshot",
        "total_buy_amount": sum(float(item["trade_amount"]) for item in orders if item["side"] == "BUY"),
        "total_sell_amount": abs(sum(float(item["trade_amount"]) for item in orders if item["side"] == "SELL")),
        "orders": sorted(orders, key=lambda row: row["symbol"]),
    }


def validate_batch_transition(current_status: str, target_status: str) -> None:
    """校验手工调仓批次状态流转。"""
    allowed = {
        ORDER_DRAFT_STATUS: {ORDER_CONFIRMED_STATUS, ORDER_CANCELLED_STATUS},
        ORDER_CONFIRMED_STATUS: {ORDER_FILLED_STATUS, ORDER_REJECTED_STATUS, ORDER_CANCELLED_STATUS},
        ORDER_FILLED_STATUS: set(),
        ORDER_REJECTED_STATUS: set(),
        ORDER_CANCELLED_STATUS: set(),
    }
    if target_status == current_status:
        return
    if target_status not in allowed.get(current_status, set()):
        raise ValueError(f"invalid manual order transition: {current_status} -> {target_status}")


def _suggest_quantity(trade_amount: float, price: float) -> int:
    """按 A 股一手 100 股估算建议数量。"""
    if price <= 0:
        return 0
    lots = int(trade_amount / price / 100)
    return max(lots * 100, 0)
