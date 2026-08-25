"""
生成上证指数双均线回测 HTML 报表

默认输出：
reports/shanghai_index_ma_report.html
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer
from backtest.benchmark import calculate_return_comparison
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.report import build_backtest_report_html
from backtest.strategies import MovingAverageCrossStrategy
from examples.shanghai_index_ma_backtest import (
    INITIAL_CAPITAL,
    LONG_WINDOW,
    SHORT_WINDOW,
    SYMBOL,
    SYMBOL_NAME,
    build_recent_month_window,
    fetch_shanghai_index_klines,
)


def run_yearly_report_backtest() -> tuple[pd.DataFrame, BacktestEngine, PerformanceAnalyzer, str]:
    """执行最近一年上证指数双均线回测，并返回报表所需对象。"""
    fetch_start, run_start, run_end = build_recent_month_window(run_days=365, warmup_days=90)
    df = fetch_shanghai_index_klines(fetch_start, run_end)

    data_manager = DataManager()
    data_manager.load_data(SYMBOL, df)

    strategy = MovingAverageCrossStrategy(
        SYMBOL,
        short_window=SHORT_WINDOW,
        long_window=LONG_WINDOW,
    )
    engine = BacktestEngine(
        data_manager=data_manager,
        strategy=strategy,
        initial_capital=INITIAL_CAPITAL,
        commission_rate=0.0003,
        slippage=0.001,
    )
    results = engine.run(
        start_date=datetime.combine(run_start, datetime.min.time()),
        end_date=datetime.combine(run_end, datetime.min.time()),
    )
    analyzer = PerformanceAnalyzer(results, engine.trades, INITIAL_CAPITAL)
    subtitle = (
        f"{SYMBOL_NAME}({SYMBOL})，MA{SHORT_WINDOW}/MA{LONG_WINDOW}，"
        f"回测区间 {run_start} 至 {run_end}"
    )
    return results, engine, analyzer, subtitle


def generate_report(output_path: Path) -> Path:
    """生成 HTML 报表文件。"""
    results, engine, analyzer, subtitle = run_yearly_report_backtest()
    summary = analyzer.get_summary()
    # 当前报表标的是上证指数自身，先把上证作为基线接入，后续其他标的复用同一字段。
    benchmark_summary = calculate_return_comparison(
        strategy_daily_values=results,
        benchmark_bars=engine.data_manager.get_data(engine.data_manager.get_symbols()[0]),
        initial_capital=INITIAL_CAPITAL,
        benchmark_name="上证指数",
    )
    summary.update({
        "基线总收益率": float(benchmark_summary["基线总收益率"]),
        "超额收益率": float(benchmark_summary["超额收益率"]),
        "基线年化收益率": float(benchmark_summary["基线年化收益率"]),
        "年化超额收益率": float(benchmark_summary["年化超额收益率"]),
    })
    html = build_backtest_report_html(
        title="上证指数双均线回测报表",
        subtitle=subtitle,
        summary=summary,
        daily_values=results,
        trades=engine.trades,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> None:
    """命令行入口。"""
    output_path = Path("reports/shanghai_index_ma_report.html")
    report_path = generate_report(output_path)
    print(f"报表已生成: {report_path.resolve()}")


if __name__ == "__main__":
    main()
