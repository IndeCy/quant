"""主线链动策略历史回测资产化。"""

from __future__ import annotations

import contextlib
from datetime import date, timedelta
import io
import sqlite3
from typing import Any

import pandas as pd

from backtest.cache import MarketDataCache
from backtest.chain_selection import ChainStockSelectionStrategy
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.execution_model import ExecutionModel
from examples.compare_chain_stock_selection import (
    ADJUST as STOCK_ADJUST,
    FREQUENCY as STOCK_FREQUENCY,
    TENCENT_PROVIDER as STOCK_PROVIDER,
    build_default_chain_definitions,
)
from examples.shanghai_index_ma_backtest import (
    ADJUST as INDEX_ADJUST,
    FREQUENCY as INDEX_FREQUENCY,
    SYMBOL as BENCHMARK_SYMBOL,
    TENCENT_PROVIDER as INDEX_PROVIDER,
)
from monitoring.metrics import build_strategy_monitor_frame
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths, get_runtime_paths

from .mainline_adapter import MAINLINE_STRATEGY_ID, MAINLINE_STRATEGY_NAME


INITIAL_CAPITAL = 1_000_000.0
MIN_HISTORY_ROWS = 120


def sync_mainline_chain_backtest_history(
    paths: RuntimePaths | None = None,
    monitoring_repository: MonitoringRepository | None = None,
) -> dict[str, Any]:
    """把主线链动 B 策略历史回测曲线写入统一监控表。

    该函数只使用本地行情缓存，不主动访问外部接口。若已存在真实模拟盘
    快照，回测历史截止到第一条快照前一个自然日，后续由 shadow live
    观察数据覆盖，避免把回测和真实观察混在同一天。
    """
    runtime_paths = paths or get_runtime_paths()
    cache_path = runtime_paths.data_dir / "market_cache.sqlite3"
    if not cache_path.exists():
        return {"status": "SKIPPED", "reason": "market_cache_missing", "rows": 0}

    first_snapshot = _first_mainline_snapshot_date(runtime_paths.paper_trading_path)
    requested_end = (first_snapshot - timedelta(days=1)) if first_snapshot else date.today()
    chains = build_default_chain_definitions()
    symbols = _chain_symbols(chains)
    cache = MarketDataCache(cache_path)
    try:
        stock_bars = _load_cached_stock_bars(cache, symbols, requested_end)
        benchmark_bars = cache.read_bars(
            INDEX_PROVIDER,
            BENCHMARK_SYMBOL,
            INDEX_FREQUENCY,
            INDEX_ADJUST,
            date(2000, 1, 1),
            requested_end,
        )
    finally:
        cache.close()

    if len(stock_bars) < len(symbols) or benchmark_bars.empty:
        return {"status": "SKIPPED", "reason": "insufficient_cache", "rows": 0}
    start = _common_start(stock_bars, benchmark_bars)
    if start is None:
        return {"status": "SKIPPED", "reason": "no_common_dates", "rows": 0}
    if len(benchmark_bars[benchmark_bars.index >= pd.Timestamp(start)]) < MIN_HISTORY_ROWS:
        return {"status": "SKIPPED", "reason": "history_too_short", "rows": 0}

    data_manager = DataManager()
    for symbol, bars in stock_bars.items():
        data_manager.load_data(symbol, bars[bars.index >= pd.Timestamp(start)])
    market = benchmark_bars[benchmark_bars.index >= pd.Timestamp(start)]
    data_manager.load_data("市场基线", market)
    strategy = ChainStockSelectionStrategy(
        chains=chains,
        mode="multi_chain",
        top_n=5,
        rebalance_frequency=5,
        momentum_windows=[60, 120],
        chain_momentum_window=60,
        chain_gate_symbol="市场基线",
    )
    engine = BacktestEngine(
        data_manager=data_manager,
        strategy=strategy,
        initial_capital=INITIAL_CAPITAL,
        execution_model=ExecutionModel(slippage_bps=10.0),
    )
    with contextlib.redirect_stdout(io.StringIO()):
        results = engine.run()
    if results.empty:
        return {"status": "SKIPPED", "reason": "empty_backtest", "rows": 0}

    daily_values = results["total_value"].astype(float)
    benchmark = market["close"].reindex(daily_values.index).ffill()
    exposure = (results["positions_value"].astype(float) / results["total_value"].replace(0, pd.NA)).fillna(0.0)
    total_cost = float(sum(float(trade.get("total_fee", 0.0)) for trade in engine.trades))
    frame = build_strategy_monitor_frame(
        strategy_id=MAINLINE_STRATEGY_ID,
        strategy_name=MAINLINE_STRATEGY_NAME,
        daily_values=daily_values,
        benchmark_values=benchmark,
        exposure=exposure,
        total_cost=total_cost,
        failed_order_count=engine.failed_trade_count,
        turnover_notional=sum(abs(float(trade.get("quantity", 0)) * float(trade.get("price", 0.0))) for trade in engine.trades),
        benchmark_id=BENCHMARK_SYMBOL,
    )
    monitor = monitoring_repository or MonitoringRepository(runtime_paths.monitoring_path)
    monitor.upsert_strategy_daily(frame)
    return {
        "status": "SUCCESS",
        "rows": int(len(frame)),
        "start": str(frame.iloc[0]["trade_date"]),
        "end": str(frame.iloc[-1]["trade_date"]),
    }


def _load_cached_stock_bars(cache: MarketDataCache, symbols: list[str], end_date: date) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        bars = cache.read_bars(
            STOCK_PROVIDER,
            symbol,
            STOCK_FREQUENCY,
            STOCK_ADJUST,
            date(2000, 1, 1),
            end_date,
        )
        if not bars.empty:
            result[symbol] = bars
    return result


def _chain_symbols(chains) -> list[str]:
    symbols: list[str] = []
    for chain in chains:
        symbols.append(chain.proxy_symbol)
        symbols.extend(stock.symbol for stock in chain.stocks)
    return list(dict.fromkeys(symbols))


def _common_start(stock_bars: dict[str, pd.DataFrame], benchmark_bars: pd.DataFrame) -> date | None:
    starts = [pd.Timestamp(frame.index.min()).date() for frame in stock_bars.values() if not frame.empty]
    if not benchmark_bars.empty:
        starts.append(pd.Timestamp(benchmark_bars.index.min()).date())
    return max(starts) if starts else None


def _first_mainline_snapshot_date(path: Any) -> date | None:
    if not path or not getattr(path, "exists", lambda: False)():
        return None
    with sqlite3.connect(path) as con:
        row = con.execute(
            """
            SELECT MIN(s.trade_date)
            FROM paper_daily_snapshot s
            JOIN paper_account a ON s.account_id = a.id
            WHERE a.strategy_code = 'Mainline_Chain_Momentum'
            """
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return pd.to_datetime(row[0]).date()
