"""T+1开盘重算 Paper 的订单差异与跟踪误差归因工具。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backtest.paper_execution import PaperOrder, PaperTradingResult
from examples.quality_defensive_assets_paper_metrics import paper_curve
from examples.strategy_comparison_research import BacktestResearchResult


def build_order_alignment(
    legacy: PaperTradingResult,
    open_aware: PaperTradingResult,
    targets: dict[str, dict[str, float]],
    market_data: pd.DataFrame,
) -> pd.DataFrame:
    """逐信号、成交日和股票对齐两种定股数政策的订单。"""
    legacy_map = {_order_key(order): order for order in legacy.orders}
    open_map = {_order_key(order): order for order in open_aware.orders}
    open_lookup = _open_price_lookup(market_data)
    execution_dates = _execution_date_by_signal(legacy, open_aware)
    missing_batches = _missing_open_batches(
        targets,
        execution_dates,
        open_lookup,
    )
    rows: list[dict[str, Any]] = []
    for key in sorted(set(legacy_map) | set(open_map)):
        signal_date, execute_date, symbol = key
        legacy_order = legacy_map.get(key)
        open_order = open_map.get(key)
        category = _order_category(
            legacy_order,
            open_order,
            signal_date in missing_batches,
        )
        open_price = float(open_lookup.get((execute_date, symbol), 0.0))
        rows.append(
            {
                "signal_date": signal_date,
                "execute_date": execute_date,
                "symbol": symbol,
                "category": category,
                "legacy_side": _text(legacy_order, "side"),
                "open_aware_side": _text(open_order, "side"),
                "legacy_quantity": _number(legacy_order, "quantity"),
                "open_aware_quantity": _number(open_order, "quantity"),
                "quantity_difference": (
                    _number(open_order, "quantity")
                    - _number(legacy_order, "quantity")
                ),
                "legacy_status": _text(legacy_order, "status"),
                "open_aware_status": _text(open_order, "status"),
                "open_price": open_price,
                "legacy_notional": (
                    _number(legacy_order, "quantity") * open_price
                ),
                "open_aware_notional": (
                    _number(open_order, "quantity") * open_price
                ),
                "batch_missing_open": signal_date in missing_batches,
            }
        )
    return pd.DataFrame(rows)


def summarize_order_alignment(
    alignment: pd.DataFrame,
    legacy: PaperTradingResult,
    open_aware: PaperTradingResult,
    m0_result: BacktestResearchResult,
) -> dict[str, Any]:
    """汇总订单数量差异是否来自真实执行失败。"""
    categories = (
        alignment.groupby("category", observed=True)
        .agg(
            order_count=("symbol", "size"),
            legacy_notional=("legacy_notional", "sum"),
            open_aware_notional=("open_aware_notional", "sum"),
        )
        .reset_index()
    )
    category_map = {
        str(row["category"]): {
            "order_count": int(row["order_count"]),
            "legacy_notional": float(row["legacy_notional"]),
            "open_aware_notional": float(row["open_aware_notional"]),
        }
        for _, row in categories.iterrows()
    }
    legacy_success = _success_count(legacy)
    open_success = _success_count(open_aware)
    legacy_rejected = _rejected_count(legacy)
    open_rejected = _rejected_count(open_aware)
    m0_success = len(m0_result.trades)
    return {
        "m0_successful_orders": m0_success,
        "legacy_generated_orders": len(legacy.orders),
        "open_aware_generated_orders": len(open_aware.orders),
        "legacy_successful_orders": legacy_success,
        "open_aware_successful_orders": open_success,
        "successful_order_gap_vs_m0": open_success - m0_success,
        "generated_order_gap_vs_legacy": len(open_aware.orders) - len(legacy.orders),
        "legacy_rejected_orders": legacy_rejected,
        "open_aware_rejected_orders": open_rejected,
        "rejected_order_change": open_rejected - legacy_rejected,
        "missing_open_batch_count": int(
            alignment.loc[
                alignment["batch_missing_open"].astype(bool),
                "signal_date",
            ].nunique()
        ),
        "category_breakdown": category_map,
    }


def build_tracking_attribution(
    m0_curve: pd.Series,
    legacy: PaperTradingResult,
    open_aware: PaperTradingResult,
) -> pd.DataFrame:
    """计算每日收益差及其对跟踪误差平方和的贡献。"""
    curves = pd.concat(
        [
            _normalize_curve(m0_curve).rename("m0"),
            _normalize_curve(paper_curve(legacy)).rename("legacy"),
            _normalize_curve(paper_curve(open_aware)).rename("open_aware"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    returns = curves.pct_change().fillna(0.0)
    frame = pd.DataFrame(index=returns.index)
    frame["m0_return"] = returns["m0"]
    frame["legacy_return"] = returns["legacy"]
    frame["open_aware_return"] = returns["open_aware"]
    frame["open_minus_m0"] = (
        frame["open_aware_return"] - frame["m0_return"]
    )
    frame["legacy_minus_m0"] = (
        frame["legacy_return"] - frame["m0_return"]
    )
    frame["open_minus_legacy"] = (
        frame["open_aware_return"] - frame["legacy_return"]
    )
    squared = frame["open_minus_m0"].pow(2)
    denominator = float(squared.sum())
    frame["tracking_squared_contribution"] = (
        squared / denominator if denominator > 0 else 0.0
    )
    execution_dates = {
        pd.Timestamp(order.execute_date)
        for order in open_aware.orders
    }
    frame["is_execution_date"] = frame.index.isin(execution_dates)
    return frame.rename_axis("trade_date").reset_index()


def summarize_tracking(frame: pd.DataFrame) -> dict[str, float]:
    """汇总误差集中度和执行日贡献。"""
    ordered = frame.sort_values(
        "tracking_squared_contribution",
        ascending=False,
    )
    contribution = frame["tracking_squared_contribution"].astype(float)
    execution_mask = frame["is_execution_date"].astype(bool)
    return {
        "top_5_dates_contribution": float(
            ordered.head(5)["tracking_squared_contribution"].sum()
        ),
        "top_10_dates_contribution": float(
            ordered.head(10)["tracking_squared_contribution"].sum()
        ),
        "execution_dates_contribution": float(
            contribution.loc[execution_mask].sum()
        ),
        "non_execution_dates_contribution": float(
            contribution.loc[~execution_mask].sum()
        ),
        "largest_daily_return_gap": float(
            frame["open_minus_m0"].abs().max()
        ),
        "tracking_error_annualized": float(
            frame["open_minus_m0"].std(ddof=1) * (252 ** 0.5)
        ),
    }


def top_tracking_dates(
    frame: pd.DataFrame,
    limit: int = 20,
) -> pd.DataFrame:
    """输出贡献最大的日期用于人工复核。"""
    return frame.sort_values(
        ["tracking_squared_contribution", "trade_date"],
        ascending=[False, True],
    ).head(limit)


def _order_key(order: PaperOrder) -> tuple[str, str, str]:
    return order.signal_date, order.execute_date, order.symbol


def _order_category(
    legacy: PaperOrder | None,
    open_aware: PaperOrder | None,
    missing_open_batch: bool,
) -> str:
    if legacy is not None and open_aware is not None:
        if legacy.side == open_aware.side:
            return "MATCHED_SAME_SIDE"
        return "DIRECTION_CHANGED"
    if legacy is not None:
        if missing_open_batch:
            return "LEGACY_ONLY_MISSING_OPEN_BATCH"
        return "LEGACY_ONLY_T1_DELTA_ZERO"
    return "OPEN_AWARE_ONLY_NEW_DELTA"


def _execution_date_by_signal(
    legacy: PaperTradingResult,
    open_aware: PaperTradingResult,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for order in [*legacy.orders, *open_aware.orders]:
        mapping.setdefault(order.signal_date, order.execute_date)
    return mapping


def _missing_open_batches(
    targets: dict[str, dict[str, float]],
    execution_dates: dict[str, str],
    open_lookup: dict[tuple[str, str], float],
) -> set[str]:
    missing: set[str] = set()
    for compact_date, weights in targets.items():
        signal_date = pd.Timestamp(compact_date).strftime("%Y-%m-%d")
        execute_date = execution_dates.get(signal_date)
        if execute_date is None:
            continue
        required = {
            symbol
            for symbol, weight in weights.items()
            if float(weight) > 0
        }
        if any(
            open_lookup.get((execute_date, symbol), 0.0) <= 0
            for symbol in required
        ):
            missing.add(signal_date)
    return missing


def _open_price_lookup(
    market_data: pd.DataFrame,
) -> dict[tuple[str, str], float]:
    frame = market_data.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame["open"] = pd.to_numeric(frame["open"], errors="coerce").fillna(0.0)
    return {
        (str(row["date"]), str(row["symbol"])): float(row["open"])
        for _, row in frame.iterrows()
        if float(row["open"]) > 0
    }


def _normalize_curve(curve: pd.Series) -> pd.Series:
    normalized = curve.astype(float).sort_index()
    return normalized / float(normalized.iloc[0])


def _success_count(result: PaperTradingResult) -> int:
    return sum(
        order.status in {"FILLED", "PARTIAL_FILLED"}
        for order in result.orders
    )


def _rejected_count(result: PaperTradingResult) -> int:
    return sum(order.status == "REJECTED" for order in result.orders)


def _text(order: PaperOrder | None, attribute: str) -> str:
    return str(getattr(order, attribute)) if order is not None else ""


def _number(order: PaperOrder | None, attribute: str) -> int:
    return int(getattr(order, attribute)) if order is not None else 0
