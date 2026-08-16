"""Quality防御组合订单数量规划的计算与报告函数。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backtest.paper_execution import BrokerConfig


ORDER_POLICIES = (
    "close_sized_current",
    "close_sized_cash_reserve_5pct",
    "open_aware_resized",
)


def build_open_aware_order_weights(
    target_weights: dict[str, float],
    signal_market: pd.DataFrame,
    execution_market: pd.DataFrame,
    capital: float,
    config: BrokerConfig,
) -> dict[str, float]:
    """按T+1可执行价重算整手股数，再映射回研究Broker的订单输入。"""
    signal_prices = _price_map(signal_market, "close")
    execution_prices = _price_map(execution_market, "open")
    quantities: dict[str, int] = {}
    for symbol, weight in target_weights.items():
        open_price = execution_prices.get(symbol, 0.0)
        fill_price = open_price * (1 + config.slippage_bps / 10_000)
        if fill_price <= 0 or weight <= 0:
            continue
        quantity = math.floor(
            capital * float(weight) / fill_price / config.lot_size
        ) * config.lot_size
        if quantity > 0:
            quantities[symbol] = quantity
    quantities = fit_quantities_to_cash(
        quantities,
        execution_prices,
        capital,
        config,
    )
    result: dict[str, float] = {}
    for symbol, quantity in quantities.items():
        signal_price = signal_prices.get(symbol, 0.0)
        if signal_price <= 0:
            continue
        # 加半股抵御浮点向下取整，不会跨越100股整手边界。
        result[symbol] = (quantity + 0.5) * signal_price / capital
    return result


def fit_quantities_to_cash(
    quantities: dict[str, int],
    open_prices: dict[str, float],
    cash: float,
    config: BrokerConfig,
) -> dict[str, int]:
    """在保留相对结构的前提下，把估算买入成本压入可用现金。"""
    current = dict(quantities)
    for _ in range(4):
        total_cost = estimate_buy_cost(current, open_prices, config)
        if total_cost <= cash + 1e-9:
            return current
        scale = max(min(cash / total_cost, 1.0), 0.0)
        current = {
            symbol: (
                math.floor(quantity * scale / config.lot_size)
                * config.lot_size
            )
            for symbol, quantity in current.items()
        }
        current = {
            symbol: quantity
            for symbol, quantity in current.items()
            if quantity > 0
        }
    return current


def estimate_buy_cost(
    quantities: dict[str, int],
    open_prices: dict[str, float],
    config: BrokerConfig,
) -> float:
    """按滑点、佣金和最低佣金估算买入占用资金。"""
    total = 0.0
    for symbol, quantity in quantities.items():
        fill_price = open_prices[symbol] * (
            1 + config.slippage_bps / 10_000
        )
        notional = quantity * fill_price
        commission = max(
            notional * config.commission_rate,
            config.min_commission,
        )
        total += notional + commission
    return total


def evaluate_order_policies(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """按拒单、目标偏离、最大单票缺口和仓位依次比较政策。"""
    production_cases = [
        item for item in cases if item["capital"] >= 500_000.0
    ]
    summaries: list[dict[str, Any]] = []
    for policy in ORDER_POLICIES:
        rows = [
            item
            for item in production_cases
            if item["order_policy"] == policy
        ]
        summaries.append(
            {
                "order_policy": policy,
                "rejected_orders": sum(
                    int(item["rejected_orders"]) for item in rows
                ),
                "worst_tracking_total_variation": max(
                    float(item["tracking_total_variation"])
                    for item in rows
                ),
                "worst_max_abs_weight_gap": max(
                    float(item["max_abs_weight_gap"]) for item in rows
                ),
                "average_gross_exposure": sum(
                    float(item["gross_exposure"]) for item in rows
                )
                / len(rows),
                "average_execution_cost": sum(
                    float(item["execution_cost"]) for item in rows
                )
                / len(rows),
            }
        )
    ranked = sorted(
        summaries,
        key=lambda item: (
            item["rejected_orders"],
            item["worst_tracking_total_variation"],
            item["worst_max_abs_weight_gap"],
            -item["average_gross_exposure"],
        ),
    )
    winner = ranked[0]["order_policy"]
    outcome = (
        "OPEN_AWARE_ORDER_SIZING_RECOMMENDED"
        if winner == "open_aware_resized"
        else "KEEP_CURRENT_ORDER_SIZING"
    )
    return {
        "policy_summary": summaries,
        "recommended_policy": winner,
        "research_outcome": outcome,
        "decision_reason": (
            f"{winner}按拒单、最差目标偏离、最大单票缺口和平均仓位排序第一"
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    """生成可归档的人类可读研究报告。"""
    policy_rows = "\n".join(
        "| {order_policy} | {rejected_orders} | "
        "{worst_tracking_total_variation:.2%} | "
        "{worst_max_abs_weight_gap:.2%} | "
        "{average_gross_exposure:.2%} | "
        "{average_execution_cost:,.2f} |".format(**item)
        for item in result["policy_summary"]
    )
    stress = [
        item
        for item in result["cases"]
        if item["scenario"] == "gap_up_5pct"
        and item["capital"] in {500_000.0, 1_000_000.0}
    ]
    stress_rows = "\n".join(
        "| {order_policy} | {capital:,.0f} | {rejected_orders} | "
        "{cash_weight:.2%} | {tracking_total_variation:.2%} | "
        "{max_abs_weight_gap:.2%} |".format(**item)
        for item in stress
    )
    return f"""# Quality防御组合T+1订单数量规划研究

- 信号日：{result['data_as_of']}
- 执行日：{result['execution_date']}
- 推荐政策：{result['recommended_policy']}
- 研究结论：{result['research_outcome']}
- 原因：{result['decision_reason']}

## 政策汇总

| 订单政策 | 拒单 | 最差目标偏离 | 最大单票缺口 | 平均仓位 | 平均成本 |
| --- | ---: | ---: | ---: | ---: | ---: |
{policy_rows}

## 5%高开压力

| 订单政策 | 本金 | 拒单 | 现金 | 目标偏离 | 最大单票缺口 |
| --- | ---: | ---: | ---: | ---: | ---: |
{stress_rows}
"""


def _price_map(frame: pd.DataFrame, column: str) -> dict[str, float]:
    return {
        str(row.symbol): float(getattr(row, column))
        for row in frame.itertuples(index=False)
    }
