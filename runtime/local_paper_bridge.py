"""策略目标组合到本地 Paper Broker 的桥接工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data.calendar import TradingCalendar
from runtime.local_paper_broker import LocalPaperBroker, PaperBrokerTarget, PaperBrokerSyncResult
from runtime.paths import RuntimePaths
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository


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
) -> PaperBrokerSyncResult:
    """把任意策略目标权重同步到统一本地模拟盘账户。"""
    broker = LocalPaperBroker(paths.paper_trading_path)
    try:
        result = broker.sync_target(
            PaperBrokerTarget(
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                trade_date=trade_date,
                target_weights=target_weights,
                market_data=market_data,
                trading_dates=next_broker_trading_dates(trade_date),
                initial_cash=initial_cash,
                benchmark_symbol=benchmark_symbol,
                benchmark_name=benchmark_name,
            )
        )
        _persist_account_snapshot(paths, broker, result, target_weights, market_data)
        return result
    finally:
        broker.close()


def _persist_account_snapshot(
    paths: RuntimePaths,
    broker: LocalPaperBroker,
    result: PaperBrokerSyncResult,
    target_weights: dict[str, float],
    market_data: pd.DataFrame,
) -> None:
    """把 Paper Broker 事实状态投影为前端统一账户快照。"""
    account = broker.store.get_account(result.account_id)
    prices = _close_prices(market_data, result.trade_date)
    actual_positions: dict[str, dict[str, Any]] = {}
    for position in broker.store.list_positions(result.account_id):
        symbol = str(position["symbol"])
        last_close = prices.get(symbol, float(position.get("avg_cost") or 0.0))
        quantity = int(position.get("quantity") or 0)
        actual_positions[symbol] = {
            "market_value": quantity * last_close,
            "quantity": quantity,
            "last_close": last_close,
        }
    cash = float(account["cash"])
    total_value = cash + sum(float(item["market_value"]) for item in actual_positions.values())
    snapshot = build_account_snapshot(
        strategy_id=str(account["strategy_code"]),
        trade_date=result.trade_date,
        total_value=total_value,
        cash=cash,
        target_weights=target_weights,
        actual_positions=actual_positions,
    )
    SystemRepository(paths.system_state_path).upsert_account_snapshot(snapshot)


def _close_prices(market_data: pd.DataFrame, trade_date: str) -> dict[str, float]:
    """提取指定交易日收盘价，缺失时由账户投影使用持仓成本兜底。"""
    if market_data.empty:
        return {}
    frame = market_data.copy()
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    frame = frame[frame["trade_date"].eq(_compact_date(trade_date))]
    return {
        str(row["symbol"]): float(row["close"])
        for _, row in frame.iterrows()
        if float(row.get("close") or 0.0) > 0
    }


def load_live_market_for_symbols(paths: RuntimePaths, trade_date: str, symbols: list[str], names: dict[str, str] | None = None) -> pd.DataFrame:
    """从统一 Tushare 增量库读取 Broker 撮合需要的日线行情。"""
    if not symbols or not paths.live_market_increment_path.exists():
        return pd.DataFrame(columns=_market_columns())
    symbol_list = sorted(set(symbols))
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
            }
        )
    return _finalize_market_frame(pd.DataFrame(rows), names or {})


def _finalize_market_frame(frame: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=_market_columns())
    result = frame.copy()
    result["name"] = result["symbol"].map(names).fillna(result.get("name", result["symbol"]))
    result["is_suspended"] = False
    result["limit_up"] = False
    result["limit_down"] = False
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
