"""
保存已验证策略到历史库的示例

示例会回测中证1000近两年 MA5/MA20，并以上证指数作为基线，
随后把结果写入 data/strategy_history.sqlite3。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer
from backtest.benchmark import calculate_return_comparison, calculate_yearly_return_comparison
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.history import StrategyHistoryStore
from backtest.strategies import MovingAverageCrossStrategy
from examples.shanghai_index_ma_backtest import (
    INITIAL_CAPITAL,
    LONG_WINDOW,
    SHORT_WINDOW,
    build_recent_month_window,
    fetch_tencent_index_klines,
)


def main() -> None:
    """执行回测并写入策略历史库。"""
    symbol = "000852.SH"
    symbol_name = "中证1000"
    benchmark_symbol = "000001.SH"
    benchmark_name = "上证指数"
    fetch_start, run_start, run_end = build_recent_month_window(run_days=365 * 2, warmup_days=90)

    target_bars = fetch_tencent_index_klines(symbol, fetch_start, run_end)
    benchmark_bars = fetch_tencent_index_klines(benchmark_symbol, fetch_start, run_end)

    data_manager = DataManager()
    data_manager.load_data(symbol, target_bars)
    strategy = MovingAverageCrossStrategy(symbol, short_window=SHORT_WINDOW, long_window=LONG_WINDOW)
    engine = BacktestEngine(data_manager, strategy, initial_capital=INITIAL_CAPITAL, commission_rate=0.0003, slippage=0.001)
    results = engine.run(
        start_date=datetime.combine(run_start, datetime.min.time()),
        end_date=datetime.combine(run_end, datetime.min.time()),
    )

    analyzer = PerformanceAnalyzer(results, engine.trades, INITIAL_CAPITAL)
    metrics = analyzer.get_summary()
    comparison = calculate_return_comparison(results, benchmark_bars, INITIAL_CAPITAL, benchmark_name=benchmark_name)
    yearly_returns = calculate_yearly_return_comparison(results, benchmark_bars, INITIAL_CAPITAL)
    metrics.update({
        "基线总收益率": comparison["基线总收益率"],
        "超额收益率": comparison["超额收益率"],
        "基线年化收益率": comparison["基线年化收益率"],
        "年化超额收益率": comparison["年化超额收益率"],
    })

    store = StrategyHistoryStore()
    try:
        run_id = store.record_run(
            symbol=symbol,
            symbol_name=symbol_name,
            strategy_name=strategy.name,
            strategy_params={"short_window": SHORT_WINDOW, "long_window": LONG_WINDOW},
            start_date=run_start.isoformat(),
            end_date=run_end.isoformat(),
            provider="tencent",
            benchmark_symbol=benchmark_symbol,
            benchmark_name=benchmark_name,
            metrics=metrics,
            yearly_returns=yearly_returns,
        )
        classified = store.classify_runs()
    finally:
        store.close()

    print(f"已写入策略历史: run_id={run_id}")
    print(f"标的分类数: {len(classified['by_symbol'])}")
    print(f"策略分类数: {len(classified['by_strategy'])}")
    print(f"年度分类数: {len(classified['by_year'])}")


if __name__ == "__main__":
    main()
