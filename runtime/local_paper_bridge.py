"""策略目标组合到本地 Paper Broker 的桥接工具。"""

from __future__ import annotations

from pathlib import Path
from dataclasses import asdict
import sqlite3
from typing import Any

import duckdb
import pandas as pd

from data.calendar import TradingCalendar
from data.market_snapshot import create_market_snapshot
from runtime.account_projection_service import project_paper_account_snapshot
from runtime.local_paper_broker import LocalPaperBroker, PaperBrokerTarget, PaperBrokerSyncResult
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.risk_policy import RiskPolicyRepository, apply_risk_cap


def next_broker_trading_dates(trade_date: str) -> list[str]:
    """返回 Broker 需要的当前交易日和下一交易日。"""
    calendar = TradingCalendar()
    next_day = calendar.next_trading_day(pd.Timestamp(trade_date))
    compact = _compact_date(trade_date)
    if next_day is None:
        return [compact]
    return [compact, next_day.strftime("%Y%m%d")]


def sync_strategy_target_to_local_paper(
    paths: RuntimePaths,
    strategy_id: str,
    strategy_name: str,
    trade_date: str,
    target_weights: dict[str, float],
    market_data: pd.DataFrame,
    initial_cash: float,
    benchmark_symbol: str,
    benchmark_name: str,
    *,
    risk_as_of_date: str | None = None,
    replace_pending_orders: bool = False,
) -> PaperBrokerSyncResult:
    """把任意策略目标权重同步到统一本地模拟盘账户。"""
    policy = RiskPolicyRepository(paths.system_state_path).resolve(strategy_id, risk_as_of_date or trade_date)
    effective_weights = apply_risk_cap(target_weights, policy.max_exposure if policy else None)
    broker = LocalPaperBroker(paths.paper_trading_path)
    try:
        result = broker.sync_target(
            PaperBrokerTarget(
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                trade_date=trade_date,
                target_weights=effective_weights,
                market_data=market_data,
                trading_dates=next_broker_trading_dates(trade_date),
                initial_cash=initial_cash,
                benchmark_symbol=benchmark_symbol,
                benchmark_name=benchmark_name,
                # 盘后策略提交只生成下一交易日订单；旧单只能由开盘撮合任务处理。
                execute_due_orders=False,
                replace_pending_orders=replace_pending_orders,
            )
        )
        project_paper_account_snapshot(
            paths,
            broker,
            result.account_id,
            result.trade_date,
            market_data,
            # 查询投影保留策略理论目标，风险上限单独展示并只约束委托。
            target_weights,
        )
        return result
    finally:
        broker.close()


def replan_paper_orders_for_risk_policy(
    paths: RuntimePaths,
    strategy_id: str,
    signal_date: str,
    effective_date: str,
) -> dict[str, Any]:
    """风险上限变化后，用最近理论目标替换未成交委托。"""
    repository = SystemRepository(paths.system_state_path)
    snapshot = repository.load_account_snapshot(strategy_id)
    if snapshot is None:
        return {"status": "SKIPPED", "message": "没有可重算的策略目标快照"}
    target_weights = {
        str(item["symbol"]): float(item.get("target_weight") or 0.0)
        for item in snapshot.get("positions", [])
        if float(item.get("target_weight") or 0.0) > 0
    }
    if not target_weights:
        return {"status": "SKIPPED", "message": "策略理论目标为空"}
    try:
        instance = repository.load_strategy_instance(strategy_id)
    except KeyError:
        instance = {"strategy_id": strategy_id, "name": strategy_id, "benchmark": "510300", "config": {}}
    symbols = sorted(set(target_weights) | _paper_account_symbols(paths, strategy_id))
    market_data = load_live_market_for_symbols(paths, signal_date, symbols)
    if market_data.empty:
        return {"status": "FAILED", "message": f"{signal_date} 行情为空，未替换原委托"}
    config = instance.get("config") if isinstance(instance.get("config"), dict) else {}
    result = sync_strategy_target_to_local_paper(
        paths=paths,
        strategy_id=strategy_id,
        strategy_name=str(instance.get("name") or strategy_id),
        trade_date=signal_date,
        target_weights=target_weights,
        market_data=market_data,
        initial_cash=float(config.get("initial_capital", 1_000_000.0)),
        benchmark_symbol=str(instance.get("benchmark") or "510300"),
        benchmark_name=str(instance.get("benchmark") or "510300"),
        risk_as_of_date=effective_date,
        replace_pending_orders=True,
    )
    return {
        "status": "SUCCESS",
        "message": (
            f"旧单取消{result.cancelled_orders}笔，新建{result.created_orders}笔，"
            f"计划{result.next_trade_date}撮合"
        ),
        **asdict(result),
    }


def _paper_account_symbols(paths: RuntimePaths, strategy_id: str) -> set[str]:
    """读取实际持仓和未成交委托标的，保证退出单也能获得行情。"""
    if not paths.paper_trading_path.exists():
        return set()
    with sqlite3.connect(paths.paper_trading_path) as con:
        account = con.execute(
            "SELECT id FROM paper_account WHERE strategy_code = ? ORDER BY id LIMIT 1",
            [strategy_id],
        ).fetchone()
        if account is None:
            return set()
        account_id = int(account[0])
        positions = con.execute(
            "SELECT symbol FROM paper_position WHERE account_id = ?",
            [account_id],
        ).fetchall()
        pending = con.execute(
            "SELECT symbol FROM paper_order WHERE account_id = ? AND status = 'PENDING'",
            [account_id],
        ).fetchall()
    return {str(row[0]) for row in positions + pending}


def load_live_market_for_symbols(paths: RuntimePaths, trade_date: str, symbols: list[str], names: dict[str, str] | None = None) -> pd.DataFrame:
    """从统一 base+increment 快照读取 Broker 撮合所需原始行情。"""
    if not symbols or not paths.live_market_increment_path.exists():
        return pd.DataFrame(columns=_market_columns())
    symbol_list = sorted(set(symbols))
    if paths.base_market_path.exists():
        frame = _load_market_from_snapshot(paths, trade_date, symbol_list)
        return _finalize_market_frame(frame, names or {})
    # 兼容尚未挂载历史基线的测试或迁移中环境；生产就绪检查会提示缺失。
    placeholders = ",".join(["?"] * len(symbol_list))
    with duckdb.connect(str(paths.live_market_increment_path), read_only=True) as con:
        frame = con.execute(
            f"""
            SELECT ts_code AS symbol, trade_date, open, high, low, close, vol AS volume, amount
            FROM daily
            WHERE trade_date = ? AND ts_code IN ({placeholders})
            ORDER BY ts_code
            """,
            [_compact_date(trade_date), *symbol_list],
        ).fetchdf()
    return _finalize_market_frame(frame, names or {})


def _load_market_from_snapshot(paths: RuntimePaths, trade_date: str, symbols: list[str]) -> pd.DataFrame:
    """一次连接批量读取快照日行情，执行价格必须保持不复权。"""
    compact_date = _compact_date(trade_date)
    snapshot = create_market_snapshot(
        paths.base_market_path,
        paths.live_market_increment_path,
        compact_date,
        lookback_start=compact_date,
        adjust_policy="none",
    )
    placeholders = ",".join(["?"] * len(symbols))
    con = snapshot.connect()
    try:
        return con.execute(
            f"""
            SELECT
                ts_code AS symbol,
                trade_date,
                open,
                high,
                low,
                close,
                vol AS volume,
                amount,
                COALESCE(vol, 0) <= 0 AS is_suspended
            FROM daily
            WHERE trade_date = ? AND ts_code IN ({placeholders})
            ORDER BY ts_code
            """,
            [compact_date, *symbols],
        ).fetchdf()
    finally:
        con.close()


def market_data_from_bars(bars: dict[str, pd.DataFrame], trade_date: str, names: dict[str, str] | None = None) -> pd.DataFrame:
    """把策略内存中的 DataFrame 行情转换成 Broker 行情格式。"""
    rows: list[dict[str, Any]] = []
    target = pd.Timestamp(trade_date).normalize()
    for symbol, frame in bars.items():
        if frame.empty:
            continue
        indexed = frame.copy()
        indexed.index = pd.to_datetime(indexed.index).normalize()
        if target not in set(indexed.index):
            continue
        row = indexed.loc[target]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        rows.append(
            {
                "symbol": symbol,
                "trade_date": _compact_date(trade_date),
                "name": (names or {}).get(symbol, symbol),
                "open": float(row.get("open", 0.0)),
                "high": float(row.get("high", row.get("open", 0.0))),
                "low": float(row.get("low", row.get("open", 0.0))),
                "close": float(row.get("close", 0.0)),
                "volume": float(row.get("volume", row.get("vol", 0.0))),
                "amount": float(row.get("amount", 0.0)),
                "is_suspended": bool(row.get("is_suspended", False)),
                "limit_up": bool(row.get("limit_up", False)),
                "limit_down": bool(row.get("limit_down", False)),
            }
        )
    return _finalize_market_frame(pd.DataFrame(rows), names or {})


def _finalize_market_frame(frame: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=_market_columns())
    result = frame.copy()
    result["name"] = result["symbol"].map(names).fillna(result.get("name", result["symbol"]))
    for column in ["is_suspended", "limit_up", "limit_down"]:
        if column not in result.columns:
            result[column] = False
        result[column] = result[column].fillna(False).astype(bool)
    return result.reindex(columns=_market_columns())


def _market_columns() -> list[str]:
    return [
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
    ]


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text
