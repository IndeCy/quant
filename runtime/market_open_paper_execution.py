"""开盘后本地模拟盘撮合任务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from backtest.fetcher import get_realtime_quote
from runtime.local_paper_broker import LocalPaperBroker
from runtime.notification_config import send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


MARKET_OPEN_EXECUTION_ID = "market_open_paper_execution"


@dataclass(frozen=True)
class MarketOpenExecutionResult:
    """开盘模拟撮合结果。"""

    trade_date: str
    status: str
    pending_orders: int
    executed_orders: int
    rejected_orders: int


def run_market_open_paper_execution(
    paths: RuntimePaths | None = None,
    trade_date: str | None = None,
    push: bool = False,
) -> MarketOpenExecutionResult:
    """使用实时行情撮合今日到期的本地 Paper Broker 委托。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = _compact_date(trade_date or datetime.now().strftime("%Y%m%d"))
    symbols = _pending_symbols(runtime_paths, target_date)
    run_dir = runtime_paths.runs_dir / target_date
    run_dir.mkdir(parents=True, exist_ok=True)
    if not symbols:
        result = MarketOpenExecutionResult(target_date, "NO_ACTION", 0, 0, 0)
        _record_run(runtime_paths, run_dir, result, "无到期开盘委托")
        return result

    market_data = fetch_realtime_market_data(symbols, target_date)
    broker = LocalPaperBroker(runtime_paths.paper_trading_path)
    try:
        executed, rejected = broker.execute_due_orders(target_date, market_data)
    finally:
        broker.close()
    pending_after = len(_pending_symbols(runtime_paths, target_date))
    status = "SUCCESS" if rejected == 0 else "WARNING"
    result = MarketOpenExecutionResult(target_date, status, len(symbols), executed, rejected)
    message = _format_message(result, pending_after)
    _record_run(runtime_paths, run_dir, result, message)
    if push:
        send_bark_notification(f"量化开盘模拟撮合{status}", message)
    return result


def fetch_realtime_market_data(symbols: list[str], trade_date: str | None = None) -> pd.DataFrame:
    """用腾讯实时报价构造 Broker 撮合行情。"""
    compact = _compact_date(trade_date or datetime.now().strftime("%Y%m%d"))
    quotes = get_realtime_quote([symbol[:6] for symbol in symbols])
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        code = symbol[:6]
        quote = quotes.get(code) or {}
        price = float(quote.get("price") or 0.0)
        open_price = float(quote.get("open") or price)
        limit_up = float(quote.get("limit_up") or 0.0)
        limit_down = float(quote.get("limit_down") or 0.0)
        rows.append(
            {
                "trade_date": compact,
                "symbol": symbol,
                "name": str(quote.get("name") or symbol),
                "open": open_price,
                "high": float(quote.get("high") or open_price),
                "low": float(quote.get("low") or open_price),
                "close": price or open_price,
                "volume": 1_000_000_000,
                "amount": float(quote.get("amount_wan") or 0.0) * 10_000,
                "is_suspended": open_price <= 0 and price <= 0,
                "limit_up": bool(limit_up and open_price >= limit_up),
                "limit_down": bool(limit_down and open_price <= limit_down),
            }
        )
    return pd.DataFrame(rows)


def _pending_symbols(paths: RuntimePaths, trade_date: str) -> list[str]:
    if not paths.paper_trading_path.exists():
        return []
    import sqlite3

    with sqlite3.connect(paths.paper_trading_path) as con:
        rows = con.execute(
            """
            SELECT DISTINCT symbol FROM paper_order
            WHERE status = 'PENDING' AND order_date <= ?
            ORDER BY symbol
            """,
            [_iso_date(trade_date)],
        ).fetchall()
    return [str(row[0]) for row in rows]


def _record_run(paths: RuntimePaths, run_dir: object, result: MarketOpenExecutionResult, message: str) -> None:
    repository = SystemRepository(paths.system_state_path)
    repository.record_strategy_run(MARKET_OPEN_EXECUTION_ID, result.trade_date, result.status, run_dir, message)
    repository.record_run_step(
        MARKET_OPEN_EXECUTION_ID,
        result.trade_date,
        1,
        "market_open_fill",
        result.status,
        message,
        run_dir,
    )


def _format_message(result: MarketOpenExecutionResult, pending_after: int) -> str:
    return "\n".join(
        [
            f"开盘模拟撮合 {result.trade_date}",
            f"- 到期委托：{result.pending_orders}",
            f"- 成交委托：{result.executed_orders}",
            f"- 拒单委托：{result.rejected_orders}",
            f"- 剩余待成交：{pending_after}",
        ]
    )


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text


def _iso_date(value: str) -> str:
    text = _compact_date(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"
