"""Quality防守袖套历史Paper回放的指标与冻结门槛。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtest.paper_drift import DriftAnalyzer
from backtest.paper_execution import PaperTradingResult
from examples.quality_factor_study_support import metric_summary
from examples.strategy_comparison_research import BacktestResearchResult


def paper_curve(result: PaperTradingResult) -> pd.Series:
    """把每日Paper快照转换成连续账户净值。"""
    return pd.Series(
        {
            pd.Timestamp(snapshot.date): float(snapshot.total_value)
            for snapshot in result.snapshots
        },
        dtype=float,
    ).sort_index()


def paper_metric_summary(
    name: str,
    result: PaperTradingResult,
    benchmark: pd.Series,
) -> dict[str, float]:
    """复用研究指标口径计算Paper收益、回撤和换手。"""
    trades = [
        {
            "date": order.execute_date,
            "price": order.fill_price,
            "quantity": (
                order.filled_quantity
                if order.side == "BUY"
                else -order.filled_quantity
            ),
            "fee": _order_cost(order.order_id, result),
        }
        for order in result.orders
        if order.status in {"FILLED", "PARTIAL_FILLED"}
    ]
    failures = [
        {
            "date": order.execute_date,
            "symbol": order.symbol,
            "reason": order.reject_reason,
        }
        for order in result.orders
        if order.status == "REJECTED"
    ]
    research_result = BacktestResearchResult(
        strategy=name,
        daily_values=paper_curve(result),
        trades=trades,
        failed_orders=failures,
        total_cost=float(result.total_execution_cost),
        turnover_notional=sum(
            abs(float(trade["price"]) * int(trade["quantity"]))
            for trade in trades
        ),
    )
    summary = metric_summary(research_result, benchmark)
    summary["total_execution_cost"] = float(result.total_execution_cost)
    return summary


def execution_diagnostics(
    result: PaperTradingResult,
    market_data: pd.DataFrame,
    backtest_curve: pd.Series,
    initial_cash: float,
) -> dict[str, float]:
    """计算填单率、漂移、跟踪误差和总执行成本。"""
    requested = sum(order.quantity for order in result.orders)
    filled = sum(order.filled_quantity for order in result.orders)
    order_count = len(result.orders)
    rejected = sum(order.status == "REJECTED" for order in result.orders)
    partial = sum(order.status == "PARTIAL_FILLED" for order in result.orders)
    normalized_backtest = backtest_curve / float(backtest_curve.iloc[0])
    curve = paper_curve(result)
    normalized_paper = curve / float(curve.iloc[0])
    curve_metrics = DriftAnalyzer().compare_curves(
        normalized_backtest,
        normalized_paper,
    )
    drifts = _position_value_drifts(result, market_data)
    return {
        "fill_rate": float(filled / requested) if requested else 1.0,
        "rejection_rate": float(rejected / order_count) if order_count else 0.0,
        "partial_order_rate": (
            float(partial / order_count) if order_count else 0.0
        ),
        "average_position_drift": float(pd.Series(drifts).mean())
        if drifts
        else 0.0,
        "max_position_drift": max(drifts, default=0.0),
        "tracking_error": curve_metrics["tracking_error"],
        "total_return_gap": (
            curve_metrics["paper_total_return"]
            - curve_metrics["backtest_total_return"]
        ),
        "execution_cost_to_initial_cash": (
            float(result.total_execution_cost / initial_cash)
            if initial_cash
            else 0.0
        ),
        "order_count": float(order_count),
    }


def evaluate_paper_gate(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """冻结基准和压力Paper场景的晋级门槛。"""
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
        "baseline_fill_rate_at_least_98pct": (
            baseline_diag["fill_rate"] >= 0.98
        ),
        "baseline_rejection_rate_below_5pct": (
            baseline_diag["rejection_rate"] <= 0.05
        ),
        "baseline_partial_orders_below_20pct": (
            baseline_diag["partial_order_rate"] <= 0.20
        ),
        "baseline_average_drift_below_5pct": (
            baseline_diag["average_position_drift"] <= 0.05
        ),
        "baseline_cost_below_25pct_initial_cash": (
            baseline_diag["execution_cost_to_initial_cash"] <= 0.25
        ),
        "stress_annual_return_at_least_9pct": (
            stress["annualized_return"] >= 0.09
        ),
        "stress_drawdown_within_25pct": stress["max_drawdown"] >= -0.25,
        "stress_sharpe_at_least_060": stress["sharpe"] >= 0.60,
        "stress_tracking_error_below_8pct": (
            stress_diag["tracking_error"] <= 0.08
        ),
        "stress_fill_rate_at_least_90pct": stress_diag["fill_rate"] >= 0.90,
        "stress_rejection_rate_below_10pct": (
            stress_diag["rejection_rate"] <= 0.10
        ),
        "stress_average_drift_below_10pct": (
            stress_diag["average_position_drift"] <= 0.10
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def incremental_execution_diagnostics(
    result: PaperTradingResult,
    market_data: pd.DataFrame,
    backtest_result: BacktestResearchResult,
    initial_cash: float,
) -> dict[str, float]:
    """只衡量Paper相对M0新增的执行损失。"""
    base = execution_diagnostics(
        result,
        market_data,
        backtest_result.daily_values,
        initial_cash,
    )
    paper_success = sum(
        order.status in {"FILLED", "PARTIAL_FILLED"}
        for order in result.orders
    )
    paper_rejected = sum(
        order.status == "REJECTED" for order in result.orders
    )
    m0_success = len(backtest_result.trades)
    m0_rejected = len(backtest_result.failed_orders)
    m0_attempts = max(m0_success + m0_rejected, 1)
    execution_dates = {
        order.execute_date
        for order in result.orders
    }
    post_execution_drifts = _position_value_drifts(
        result,
        market_data,
        allowed_dates=execution_dates,
    )
    latest_drift = _position_value_drifts(
        result,
        market_data,
        allowed_dates={result.snapshots[-1].date} if result.snapshots else set(),
    )
    return {
        **base,
        "m0_successful_orders": float(m0_success),
        "m0_rejected_orders": float(m0_rejected),
        "paper_successful_orders": float(paper_success),
        "paper_rejected_orders": float(paper_rejected),
        "successful_order_ratio_vs_m0": (
            float(paper_success / m0_success) if m0_success else 1.0
        ),
        "incremental_rejection_rate_vs_m0": float(
            max(paper_rejected - m0_rejected, 0) / m0_attempts
        ),
        "average_post_execution_drift": (
            float(pd.Series(post_execution_drifts).mean())
            if post_execution_drifts
            else 0.0
        ),
        "max_post_execution_drift": max(post_execution_drifts, default=0.0),
        "latest_position_drift": latest_drift[-1] if latest_drift else 0.0,
    }


def evaluate_incremental_paper_gate(
    m0_metrics: dict[str, float],
    paper_metrics: dict[str, dict[str, float]],
    diagnostics: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """冻结相对M0增量执行偏差门槛。"""
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
        "baseline_post_execution_drift_below_5pct": (
            baseline_diag["average_post_execution_drift"] <= 0.05
        ),
        "baseline_latest_drift_below_5pct": (
            baseline_diag["latest_position_drift"] <= 0.05
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
        "stress_post_execution_drift_below_10pct": (
            stress_diag["average_post_execution_drift"] <= 0.10
        ),
        "stress_latest_drift_below_10pct": (
            stress_diag["latest_position_drift"] <= 0.10
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _order_cost(order_id: int, result: PaperTradingResult) -> float:
    """按委托关联成交成本。"""
    for log in result.executions:
        if log.order_id == order_id:
            return float(log.execution_impact + log.commission + log.stamp_tax)
    return 0.0


def _position_value_drifts(
    result: PaperTradingResult,
    market_data: pd.DataFrame,
    *,
    allowed_dates: set[str] | None = None,
) -> list[float]:
    """用收盘价计算每日目标与实际持仓的市值偏离。"""
    frame = position_value_drift_frame(
        result,
        market_data,
        allowed_dates=allowed_dates,
    )
    if frame.empty:
        return []
    return frame["position_drift"].astype(float).tolist()


def position_value_drift_frame(
    result: PaperTradingResult,
    market_data: pd.DataFrame,
    *,
    allowed_dates: set[str] | None = None,
) -> pd.DataFrame:
    """输出可归因的逐日持仓市值漂移。"""
    frame = market_data.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    closes = frame.pivot_table(
        index="date",
        columns="symbol",
        values="close",
        aggfunc="last",
    ).sort_index().ffill()
    rows: list[dict[str, float | str]] = []
    for snapshot in result.snapshots:
        if allowed_dates is not None and snapshot.date not in allowed_dates:
            continue
        if snapshot.date not in closes.index:
            continue
        prices = closes.loc[snapshot.date]
        symbols = set(snapshot.target_holdings) | set(snapshot.actual_holdings)
        deviation = sum(
            abs(
                snapshot.actual_holdings.get(symbol, 0)
                - snapshot.target_holdings.get(symbol, 0)
            )
            * float(prices.get(symbol, 0.0) or 0.0)
            for symbol in symbols
        )
        rows.append(
            {
                "trade_date": snapshot.date,
                "position_drift": float(
                    deviation / max(snapshot.total_value, 1.0)
                ),
                "total_value": float(snapshot.total_value),
                "target_symbol_count": float(len(snapshot.target_holdings)),
                "actual_symbol_count": float(len(snapshot.actual_holdings)),
            }
        )
    return pd.DataFrame(rows)
