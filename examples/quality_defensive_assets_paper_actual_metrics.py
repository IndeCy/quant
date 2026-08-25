"""Paper实际账户与M0实际账户的持仓差异指标。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtest.paper_execution import PaperTradingResult
from examples.quality_defensive_assets_paper_metrics import (
    incremental_execution_diagnostics,
)
from examples.strategy_comparison_research import BacktestResearchResult


def actual_account_diagnostics(
    result: PaperTradingResult,
    market_data: pd.DataFrame,
    backtest_result: BacktestResearchResult,
    initial_cash: float,
) -> dict[str, float]:
    """比较Paper实际持仓与M0实际成交后持仓。"""
    base = incremental_execution_diagnostics(
        result,
        market_data,
        backtest_result,
        initial_cash,
    )
    execution_dates = {order.execute_date for order in result.orders}
    gaps = actual_position_gap_frame(
        result,
        market_data,
        backtest_result,
        allowed_dates=execution_dates,
    )
    latest = actual_position_gap_frame(
        result,
        market_data,
        backtest_result,
        allowed_dates={result.snapshots[-1].date} if result.snapshots else set(),
    )
    return {
        **base,
        "average_actual_position_gap": (
            float(gaps["position_gap"].mean()) if not gaps.empty else 0.0
        ),
        "max_actual_position_gap": (
            float(gaps["position_gap"].max()) if not gaps.empty else 0.0
        ),
        "latest_actual_position_gap": (
            float(latest["position_gap"].iloc[-1]) if not latest.empty else 0.0
        ),
    }


def evaluate_actual_account_gate(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """冻结Paper实际账户相对M0实际账户的门槛。"""
    baseline = paper_metrics["paper_baseline"]
    stress = paper_metrics["paper_stress"]
    baseline_diag = diagnostics["paper_baseline"]
    stress_diag = diagnostics["paper_stress"]
    checks = {
        "baseline_return_within_2pct_of_m0": (
            baseline["annualized_return"]
            >= m0_metrics["annualized_return"] - 0.02
        ),
        "baseline_drawdown_within_3pct_of_m0": (
            baseline["max_drawdown"] >= m0_metrics["max_drawdown"] - 0.03
        ),
        "baseline_sharpe_within_010_of_m0": (
            baseline["sharpe"] >= m0_metrics["sharpe"] - 0.10
        ),
        "baseline_tracking_error_below_5pct": (
            baseline_diag["tracking_error"] <= 0.05
        ),
        "baseline_success_orders_at_least_98pct_of_m0": (
            baseline_diag["successful_order_ratio_vs_m0"] >= 0.98
        ),
        "baseline_incremental_rejections_below_2pct": (
            baseline_diag["incremental_rejection_rate_vs_m0"] <= 0.02
        ),
        "baseline_actual_position_gap_below_5pct": (
            baseline_diag["average_actual_position_gap"] <= 0.05
        ),
        "baseline_latest_actual_gap_below_5pct": (
            baseline_diag["latest_actual_position_gap"] <= 0.05
        ),
        "stress_annual_return_at_least_9pct": (
            stress["annualized_return"] >= 0.09
        ),
        "stress_drawdown_within_25pct": stress["max_drawdown"] >= -0.25,
        "stress_sharpe_at_least_060": stress["sharpe"] >= 0.60,
        "stress_tracking_error_below_8pct": (
            stress_diag["tracking_error"] <= 0.08
        ),
        "stress_success_orders_at_least_95pct_of_m0": (
            stress_diag["successful_order_ratio_vs_m0"] >= 0.95
        ),
        "stress_incremental_rejections_below_5pct": (
            stress_diag["incremental_rejection_rate_vs_m0"] <= 0.05
        ),
        "stress_actual_position_gap_below_10pct": (
            stress_diag["average_actual_position_gap"] <= 0.10
        ),
        "stress_latest_actual_gap_below_10pct": (
            stress_diag["latest_actual_position_gap"] <= 0.10
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def actual_position_gap_frame(
    result: PaperTradingResult,
    market_data: pd.DataFrame,
    backtest_result: BacktestResearchResult,
    *,
    allowed_dates: set[str] | None = None,
) -> pd.DataFrame:
    """重建M0每日实际持仓，并与Paper实际账户比较。"""
    frame = market_data.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    closes = frame.pivot_table(
        index="date",
        columns="symbol",
        values="close",
        aggfunc="last",
    ).sort_index().ffill()
    trades_by_date: dict[str, list[dict[str, object]]] = {}
    for trade in backtest_result.trades:
        date = pd.Timestamp(trade["date"]).strftime("%Y-%m-%d")
        trades_by_date.setdefault(date, []).append(trade)
    m0_holdings: dict[str, int] = {}
    rows: list[dict[str, float | str]] = []
    for snapshot in sorted(result.snapshots, key=lambda item: item.date):
        for trade in trades_by_date.get(snapshot.date, []):
            symbol = str(trade["symbol"])
            m0_holdings[symbol] = (
                m0_holdings.get(symbol, 0) + int(trade["quantity"])
            )
            if m0_holdings[symbol] == 0:
                m0_holdings.pop(symbol)
        if allowed_dates is not None and snapshot.date not in allowed_dates:
            continue
        if snapshot.date not in closes.index:
            continue
        prices = closes.loc[snapshot.date]
        symbols = set(m0_holdings) | set(snapshot.actual_holdings)
        difference = sum(
            abs(
                snapshot.actual_holdings.get(symbol, 0)
                - m0_holdings.get(symbol, 0)
            )
            * float(prices.get(symbol, 0.0) or 0.0)
            for symbol in symbols
        )
        rows.append(
            {
                "trade_date": snapshot.date,
                "position_gap": float(
                    difference / max(snapshot.total_value, 1.0)
                ),
                "paper_symbol_count": float(len(snapshot.actual_holdings)),
                "m0_symbol_count": float(len(m0_holdings)),
            }
        )
    return pd.DataFrame(rows)
