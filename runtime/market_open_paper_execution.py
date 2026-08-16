"""开盘后本地模拟盘撮合任务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3
from typing import Any

import pandas as pd

from backtest.fetcher import get_realtime_quote
from runtime.account_projection_service import project_paper_account_snapshot
from runtime.local_paper_broker import LocalPaperBroker
from runtime.notification_config import send_bark_notification
from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository
from runtime.risk_confirmation import (
    blocked_strategy_ids,
    build_risk_confirmation_state,
    risk_reduction_targets,
)


MARKET_OPEN_EXECUTION_ID = "market_open_paper_execution"


@dataclass(frozen=True)
class MarketOpenExecutionResult:
    """开盘模拟撮合结果。"""

    trade_date: str
    status: str
    pending_orders: int
    executed_orders: int
    rejected_orders: int
    blocked_orders: int = 0
    cancelled_orders: int = 0
    risk_reduction_orders: int = 0
    resized_orders: int = 0
    resize_failures: int = 0


def run_market_open_paper_execution(
    paths: RuntimePaths | None = None,
    trade_date: str | None = None,
    push: bool = False,
) -> MarketOpenExecutionResult:
    """使用实时行情撮合今日到期的本地 Paper Broker 委托。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    target_date = _compact_date(trade_date or datetime.now().strftime("%Y%m%d"))
    pending_symbols = _pending_symbols(runtime_paths, target_date)
    due_account_ids = _due_account_ids(runtime_paths, target_date)
    run_dir = runtime_paths.runs_dir / target_date
    run_dir.mkdir(parents=True, exist_ok=True)

    confirmation = build_risk_confirmation_state(runtime_paths, target_date)
    reduction_targets = risk_reduction_targets(confirmation)
    reduction_account_ids = _account_ids_for_strategies(runtime_paths, set(reduction_targets))
    account_ids = sorted(set(due_account_ids) | set(reduction_account_ids))
    if not pending_symbols and not reduction_account_ids:
        result = MarketOpenExecutionResult(target_date, "NO_ACTION", 0, 0, 0)
        _record_run(runtime_paths, run_dir, result, "无到期开盘委托")
        return result

    blocked_strategies = blocked_strategy_ids(confirmation)
    account_strategies = _account_strategy_codes(runtime_paths, account_ids)
    blocked_accounts = {account_id for account_id, strategy_id in account_strategies.items() if strategy_id in blocked_strategies}
    allowed_accounts = [account_id for account_id in account_ids if account_id not in blocked_accounts]
    blocked_orders = _pending_order_count(runtime_paths, target_date, blocked_accounts)
    if not allowed_accounts:
        result = MarketOpenExecutionResult(
            target_date,
            "BLOCKED",
            len(pending_symbols),
            0,
            0,
            blocked_orders,
        )
        message = _format_message(result, len(pending_symbols))
        _record_run(runtime_paths, run_dir, result, message)
        if push:
            send_bark_notification("量化开盘模拟撮合BLOCKED", message)
        return result

    valuation_symbols = _account_symbols(runtime_paths, allowed_accounts)
    market_data = fetch_realtime_market_data(valuation_symbols, target_date)
    broker = LocalPaperBroker(runtime_paths.paper_trading_path)
    try:
        cancelled_orders = 0
        risk_reduction_orders = 0
        resized_orders = 0
        resize_failures = 0
        executable_accounts: list[int] = []
        for account_id in allowed_accounts:
            strategy_id = account_strategies.get(account_id, "")
            if strategy_id not in reduction_targets:
                resize = broker.resize_due_orders(
                    account_id,
                    target_date,
                    market_data,
                )
                if resize.status == "FAILED":
                    resize_failures += 1
                    continue
                if resize.status == "PARTIAL":
                    resize_failures += 1
                resized_orders += resize.created_orders
                executable_accounts.append(account_id)
                continue
            plan = broker.prepare_risk_reduction(
                account_id=account_id,
                trade_date=target_date,
                signal_date=str(confirmation["previous_trade_date"]),
                target_exposure=reduction_targets[strategy_id],
                market_data=market_data,
            )
            cancelled_orders += plan.cancelled_orders
            risk_reduction_orders += plan.created_orders
            executable_accounts.append(account_id)
        executed, rejected = broker.execute_due_orders(
            target_date,
            market_data,
            executable_accounts,
        )
        for account_id in allowed_accounts:
            project_paper_account_snapshot(runtime_paths, broker, account_id, target_date, market_data)
    finally:
        broker.close()
    pending_after = len(_pending_symbols(runtime_paths, target_date))
    status = (
        "SUCCESS"
        if rejected == 0 and blocked_orders == 0 and resize_failures == 0
        else "WARNING"
    )
    result = MarketOpenExecutionResult(
        target_date,
        status,
        len(pending_symbols),
        executed,
        rejected,
        blocked_orders,
        cancelled_orders,
        risk_reduction_orders,
        resized_orders,
        resize_failures,
    )
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
                "volume": float(quote.get("volume_lots") or 0.0) * 100.0,
                "amount": float(quote.get("amount_wan") or 0.0) * 10_000,
                "is_suspended": open_price <= 0 and price <= 0,
                "limit_up": bool(limit_up and open_price >= limit_up),
                "limit_down": bool(limit_down and open_price <= limit_down),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "trade_date",
            "symbol",
            "name",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "is_suspended",
            "limit_up",
            "limit_down",
        ],
    )


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
        batches = _target_batch_rows(
            con,
            """
            SELECT target_weights FROM paper_target_batch
            WHERE status IN ('PENDING', 'PARTIAL') AND execute_date <= ?
            """,
            [_iso_date(trade_date)],
        )
    symbols = {str(row[0]) for row in rows}
    symbols.update(_target_batch_symbols(batches))
    return sorted(symbols)


def _due_account_ids(paths: RuntimePaths, trade_date: str) -> list[int]:
    """返回今日存在到期委托的账户，成交后只刷新这些账户投影。"""
    if not paths.paper_trading_path.exists():
        return []
    import sqlite3

    with sqlite3.connect(paths.paper_trading_path) as con:
        rows = con.execute(
            """
            SELECT account_id FROM paper_order
            WHERE status = 'PENDING' AND order_date <= ?
            ORDER BY account_id
            """,
            [_iso_date(trade_date)],
        ).fetchall()
        batch_accounts = _target_batch_rows(
            con,
            """
            SELECT account_id FROM paper_target_batch
            WHERE status IN ('PENDING', 'PARTIAL') AND execute_date <= ?
            """,
            [_iso_date(trade_date)],
        )
    return sorted({int(row[0]) for row in [*rows, *batch_accounts]})


def _account_strategy_codes(paths: RuntimePaths, account_ids: list[int]) -> dict[int, str]:
    """读取模拟账户对应的策略，供盘前风险门禁逐策略放行。"""
    if not account_ids or not paths.paper_trading_path.exists():
        return {}
    import sqlite3

    placeholders = ",".join("?" for _ in account_ids)
    with sqlite3.connect(paths.paper_trading_path) as con:
        rows = con.execute(
            f"SELECT id, strategy_code FROM paper_account WHERE id IN ({placeholders})",
            account_ids,
        ).fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def _account_ids_for_strategies(paths: RuntimePaths, strategy_ids: set[str]) -> list[int]:
    """读取需要主动风险减仓的策略账户，即使当天原本没有调仓单。"""
    if not strategy_ids or not paths.paper_trading_path.exists():
        return []
    import sqlite3

    ordered_ids = sorted(strategy_ids)
    placeholders = ",".join("?" for _ in ordered_ids)
    with sqlite3.connect(paths.paper_trading_path) as con:
        rows = con.execute(
            f"SELECT id FROM paper_account WHERE strategy_code IN ({placeholders}) ORDER BY id",
            ordered_ids,
        ).fetchall()
    return [int(row[0]) for row in rows]


def _pending_order_count(paths: RuntimePaths, trade_date: str, account_ids: set[int]) -> int:
    """统计被门禁拦截的到期委托数量。"""
    if not account_ids or not paths.paper_trading_path.exists():
        return 0
    import sqlite3

    ordered_ids = sorted(account_ids)
    placeholders = ",".join("?" for _ in ordered_ids)
    with sqlite3.connect(paths.paper_trading_path) as con:
        row = con.execute(
            f"""
            SELECT COUNT(*) FROM paper_order
            WHERE status = 'PENDING' AND order_date <= ? AND account_id IN ({placeholders})
            """,
            [_iso_date(trade_date), *ordered_ids],
        ).fetchone()
    return int(row[0]) if row else 0


def _account_symbols(paths: RuntimePaths, account_ids: list[int]) -> list[str]:
    """读取受影响账户的持仓与待成交标的，保证投影估值覆盖完整。"""
    if not account_ids or not paths.paper_trading_path.exists():
        return []
    import sqlite3

    placeholders = ",".join("?" for _ in account_ids)
    with sqlite3.connect(paths.paper_trading_path) as con:
        rows = con.execute(
            f"""
            SELECT symbol FROM paper_position WHERE account_id IN ({placeholders})
            UNION
            SELECT symbol FROM paper_order
            WHERE account_id IN ({placeholders}) AND status = 'PENDING'
            ORDER BY symbol
            """,
            [*account_ids, *account_ids],
        ).fetchall()
        batches = _target_batch_rows(
            con,
            f"""
            SELECT target_weights FROM paper_target_batch
            WHERE account_id IN ({placeholders})
              AND status IN ('PENDING', 'PARTIAL')
            """,
            account_ids,
        )
    symbols = {str(row[0]) for row in rows}
    symbols.update(_target_batch_symbols(batches))
    return sorted(symbols)


def _target_batch_symbols(rows: list[object]) -> set[str]:
    """从待执行目标批次中提取股票代码，确保延期批次次日仍可重试。"""
    symbols: set[str] = set()
    for row in rows:
        payload = str(row[0] or "{}")
        symbols.update(str(symbol) for symbol in json.loads(payload))
    return symbols


def _target_batch_rows(
    connection: sqlite3.Connection,
    sql: str,
    params: list[object],
) -> list[object]:
    """旧Paper库没有目标批次表时按空集合兼容读取。"""
    table = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'paper_target_batch'
        """
    ).fetchone()
    if table is None:
        return []
    return list(connection.execute(sql, params).fetchall())


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
            f"- 风险门禁拦截：{result.blocked_orders}",
            f"- 风险减仓取消原单：{result.cancelled_orders}",
            f"- 风险减仓生成卖单：{result.risk_reduction_orders}",
            f"- 开盘重建订单：{result.resized_orders}",
            f"- 开盘重建失败：{result.resize_failures}",
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
