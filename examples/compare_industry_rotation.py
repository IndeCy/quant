"""
行业动量轮动对比工具

当前入口支持传入行业指数K线字典，后续可替换为真实行业指数或行业ETF数据源。
"""

from __future__ import annotations

import os
import sys
import argparse
from datetime import date, timedelta
from typing import Dict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer
from backtest.benchmark import calculate_return_comparison
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.history import StrategyHistoryStore
from backtest.history_recorder import record_comparison_results
from backtest.industry_proxy import fetch_default_industry_proxy_bars
from backtest.rotation import IndustryMomentumRotationStrategy
from examples.shanghai_index_ma_backtest import SYMBOL, fetch_tencent_index_klines


INITIAL_CAPITAL = 1000000


def _ensure_ohlcv(bars: pd.DataFrame) -> pd.DataFrame:
    """补齐回测引擎需要的 OHLCV 字段。"""
    result = bars.copy()
    if "close" not in result.columns:
        raise ValueError("行业K线必须包含 close 列")
    for column in ["open", "high", "low"]:
        if column not in result.columns:
            result[column] = result["close"]
    if "volume" not in result.columns:
        result["volume"] = 0
    return result[["open", "high", "low", "close", "volume"]]


def run_industry_rotation_comparison(
    industry_bars: Dict[str, pd.DataFrame],
    market_bars: pd.DataFrame,
    initial_capital: float = INITIAL_CAPITAL,
) -> pd.DataFrame:
    """运行行业动量轮动，并和市场基线收益对比。"""
    data_manager = DataManager()
    for symbol, bars in industry_bars.items():
        data_manager.load_data(symbol, _ensure_ohlcv(bars))
    data_manager.load_data("市场基线", _ensure_ohlcv(market_bars))

    strategy = IndustryMomentumRotationStrategy(
        symbols=list(industry_bars.keys()),
        lookback_period=60,
        top_n=4,
        rebalance_frequency=5,
        market_filter_symbol="市场基线",
        market_ma_window=120,
        industry_ma_window=60,
        use_target_weight=True,
        momentum_windows=[60, 120],
        holding_buffer_rank=5,
    )
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
        benchmark_bars=market_bars,
        initial_capital=initial_capital,
        benchmark_name="市场基线",
    )
    return pd.DataFrame(
        [
            {
                "策略": strategy.name,
                "总收益率": float(summary["总收益率"]),
                "年化收益率": float(summary["年化收益率"]),
                "最大回撤": float(summary["最大回撤"]),
                "夏普比率": float(summary["夏普比率"]),
                "交易次数": int(summary["交易次数"]),
                "基线收益率": float(benchmark["基线总收益率"]),
                "超额收益率": float(benchmark["超额收益率"]),
            }
        ]
    )


def build_real_proxy_rotation_inputs(
    fetch_start: date,
    fetch_end: date,
    market_bars: pd.DataFrame | None = None,
) -> tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """拉取真实行业 ETF 代理池和市场基线行情。"""
    industry_bars = fetch_default_industry_proxy_bars(fetch_start, fetch_end)
    benchmark_bars = market_bars
    if benchmark_bars is None:
        benchmark_bars = fetch_tencent_index_klines(SYMBOL, fetch_start=fetch_start, fetch_end=fetch_end)
    return industry_bars, benchmark_bars


def format_rotation_result(result: pd.DataFrame) -> str:
    """格式化行业轮动对比结果，方便命令行阅读。"""
    display = result.copy()
    percent_columns = ["总收益率", "年化收益率", "最大回撤", "基线收益率", "超额收益率"]
    for column in percent_columns:
        display[column] = display[column].map(lambda value: f"{value:.2%}")
    display["夏普比率"] = display["夏普比率"].map(lambda value: f"{value:.2f}")
    return display.to_string(index=False)


def build_demo_industry_bars() -> tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """构造可直接运行的行业轮动样例数据。"""
    dates = pd.date_range(start="2025-01-01", periods=120, freq="D")
    industry_bars = {
        "电力": pd.DataFrame({"close": [100 + i * 0.5 for i in range(120)]}, index=dates),
        "半导体": pd.DataFrame({"close": [100 + i * 0.8 for i in range(120)]}, index=dates),
        "银行": pd.DataFrame({"close": [100 + i * 0.2 for i in range(120)]}, index=dates),
    }
    market_bars = pd.DataFrame({"close": [100 + i * 0.4 for i in range(120)]}, index=dates)
    return industry_bars, market_bars


def main() -> None:
    """命令行入口，默认使用近一年真实行业 ETF 代理池。"""
    parser = argparse.ArgumentParser(description="行业 ETF 代理轮动回测")
    parser.add_argument("--days", type=int, default=365, help="回测自然日长度，默认365")
    parser.add_argument("--save-history", action="store_true", help="将本次轮动结果写入策略历史库")
    args = parser.parse_args()

    fetch_end = date.today()
    fetch_start = fetch_end - timedelta(days=args.days)
    industry_bars, market_bars = build_real_proxy_rotation_inputs(fetch_start, fetch_end)
    result = run_industry_rotation_comparison(industry_bars, market_bars)
    print(f"行业 ETF 代理轮动回测，区间 {fetch_start} 至 {fetch_end}")
    print(format_rotation_result(result))
    if args.save_history:
        store = StrategyHistoryStore()
        try:
            run_ids = record_comparison_results(
                store=store,
                comparison=result.assign(策略类型="行业轮动"),
                symbol="INDUSTRY_PROXY_ETF_POOL",
                symbol_name="行业ETF代理池",
                start_date=fetch_start.isoformat(),
                end_date=fetch_end.isoformat(),
                provider="tencent",
                benchmark_symbol="000001.SH",
                benchmark_name="上证指数",
                strategy_params={
                    "source": "industry_rotation_comparison",
                    "lookback_period": 60,
                    "top_n": 4,
                    "rebalance_frequency": 5,
                    "market_ma_window": 120,
                    "industry_ma_window": 60,
                    "use_target_weight": True,
                    "momentum_windows": [60, 120],
                    "holding_buffer_rank": 5,
                },
            )
        finally:
            store.close()
        print(f"已写入策略历史: {len(run_ids)} 条")


if __name__ == "__main__":
    main()
