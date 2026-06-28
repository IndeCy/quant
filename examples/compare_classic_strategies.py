"""
经典策略批量对比工具

用于把买入持有、双均线、唐奇安、海龟、RSI、布林带放到同一标的下对比。
"""

from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime
from typing import List

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer
from backtest.benchmark import calculate_return_comparison
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.history import StrategyHistoryStore
from backtest.history_recorder import record_comparison_results
from backtest.strategy import BaseStrategy
from backtest.strategies import (
    BollingerBandStrategy,
    BuyAndHoldStrategy,
    DonchianChannelBreakoutStrategy,
    MovingAverageCrossStrategy,
    RSIStrategy,
    TurtleTradingStrategy,
)
from examples.shanghai_index_ma_backtest import (
    INITIAL_CAPITAL,
    SYMBOL,
    SYMBOL_NAME,
    build_recent_month_window,
    fetch_tencent_index_klines,
)


def build_classic_strategy_suite(symbol: str) -> List[BaseStrategy]:
    """构建经典策略集合，参数先使用稳健的默认值。"""
    return [
        BuyAndHoldStrategy(symbol),
        MovingAverageCrossStrategy(symbol, short_window=5, long_window=20),
        DonchianChannelBreakoutStrategy(symbol, entry_window=20, exit_window=10),
        TurtleTradingStrategy(symbol, entry_window=20, exit_window=10, atr_window=14),
        RSIStrategy(symbol, window=14, oversold=30, overbought=70),
        BollingerBandStrategy(symbol, window=20, num_std=2.0, mode="reversion"),
        BollingerBandStrategy(symbol, window=20, num_std=2.0, mode="breakout"),
    ]


def _run_single_strategy(
    symbol: str,
    bars: pd.DataFrame,
    strategy: BaseStrategy,
    initial_capital: float,
) -> dict:
    """执行单个策略，并返回统一绩效字段。"""
    data_manager = DataManager()
    data_manager.load_data(symbol, bars)
    engine = BacktestEngine(
        data_manager=data_manager,
        strategy=strategy,
        initial_capital=initial_capital,
        commission_rate=0.0003,
        slippage=0.001,
    )
    results = engine.run()
    analyzer = PerformanceAnalyzer(results, engine.trades, initial_capital)
    summary = analyzer.get_summary()
    benchmark = calculate_return_comparison(
        strategy_daily_values=results,
        benchmark_bars=bars,
        initial_capital=initial_capital,
        benchmark_name="买入持有",
    )
    return {
        "策略": strategy.name,
        "策略类型": strategy.parameters.get("strategy_type", "基线"),
        "总收益率": float(summary["总收益率"]),
        "年化收益率": float(summary["年化收益率"]),
        "最大回撤": float(summary["最大回撤"]),
        "夏普比率": float(summary["夏普比率"]),
        "胜率": float(summary["胜率"]),
        "波动率": float(summary["波动率"]),
        "交易次数": int(summary["交易次数"]),
        "最终资产": float(summary["最终资产"]),
        "买入持有收益率": float(benchmark["基线总收益率"]),
        "超额收益率": float(benchmark["超额收益率"]),
    }


def run_strategy_comparison(
    symbol: str,
    bars: pd.DataFrame,
    initial_capital: float = INITIAL_CAPITAL,
) -> pd.DataFrame:
    """批量运行经典策略，返回按总收益率排序的对比表。"""
    rows = [
        _run_single_strategy(symbol, bars, strategy, initial_capital)
        for strategy in build_classic_strategy_suite(symbol)
    ]
    return pd.DataFrame(rows).sort_values("总收益率", ascending=False).reset_index(drop=True)


def format_comparison_table(comparison: pd.DataFrame) -> str:
    """把收益率字段格式化为适合命令行阅读的表格。"""
    display = comparison.copy()
    percent_columns = ["总收益率", "年化收益率", "最大回撤", "胜率", "波动率", "买入持有收益率", "超额收益率"]
    for column in percent_columns:
        display[column] = display[column].map(lambda value: f"{value:.2%}")
    display["夏普比率"] = display["夏普比率"].map(lambda value: f"{value:.2f}")
    display["最终资产"] = display["最终资产"].map(lambda value: f"{value:,.2f}")
    return display.to_string(index=False)


def main() -> None:
    """命令行入口，默认对比近一年上证指数。"""
    parser = argparse.ArgumentParser(description="经典策略批量对比")
    parser.add_argument("--save-history", action="store_true", help="将本次对比结果写入策略历史库")
    args = parser.parse_args()

    fetch_start, run_start, run_end = build_recent_month_window(run_days=365, warmup_days=90)
    bars = fetch_tencent_index_klines(SYMBOL, fetch_start=fetch_start, fetch_end=run_end)
    run_bars = bars[
        (bars.index >= pd.Timestamp(datetime.combine(run_start, datetime.min.time())))
        & (bars.index <= pd.Timestamp(datetime.combine(run_end, datetime.min.time())))
    ]
    comparison = run_strategy_comparison(SYMBOL, run_bars)
    print(f"{SYMBOL_NAME}({SYMBOL}) 经典策略对比，区间 {run_start} 至 {run_end}")
    print(format_comparison_table(comparison))
    if args.save_history:
        store = StrategyHistoryStore()
        try:
            run_ids = record_comparison_results(
                store=store,
                comparison=comparison,
                symbol=SYMBOL,
                symbol_name=SYMBOL_NAME,
                start_date=run_start.isoformat(),
                end_date=run_end.isoformat(),
                provider="tencent",
                benchmark_symbol=SYMBOL,
                benchmark_name=SYMBOL_NAME,
                strategy_params={"source": "classic_strategy_comparison"},
            )
        finally:
            store.close()
        print(f"已写入策略历史: {len(run_ids)} 条")


if __name__ == "__main__":
    main()
