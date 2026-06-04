"""
产业链选股 ABC 对比工具

A：指定半导体产业链，链内选股。
B：多产业链先竞争，再在强链内选股。
C：忽略产业链，全股票池强势股选择。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Dict, Iterable, List
from urllib.request import Request, urlopen

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.analysis import PerformanceAnalyzer
from backtest.benchmark import calculate_return_comparison
from backtest.cache import DEFAULT_CACHE_PATH, MarketDataCache, load_or_fetch_ohlcv
from backtest.chain_selection import ChainDefinition, ChainStock, ChainStockSelectionStrategy
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from examples.shanghai_index_ma_backtest import SYMBOL, fetch_tencent_index_klines, parse_tencent_klines


INITIAL_CAPITAL = 1_000_000.0
TENCENT_PROVIDER = "tencent"
FREQUENCY = "1d"
ADJUST = "qfq"


def build_default_chain_definitions() -> List[ChainDefinition]:
    """构建默认产业链股票池，第一版优先覆盖高关注度的大 A 标的。"""
    return [
        ChainDefinition(
            name="半导体",
            proxy_symbol="159995.SZ",
            stocks=[
                ChainStock("688012.SH", "中微公司", "半导体", "设备"),
                ChainStock("002371.SZ", "北方华创", "半导体", "设备"),
                ChainStock("688008.SH", "澜起科技", "半导体", "设计"),
                ChainStock("603986.SH", "兆易创新", "半导体", "设计"),
                ChainStock("600584.SH", "长电科技", "半导体", "封测"),
                ChainStock("002156.SZ", "通富微电", "半导体", "封测"),
            ],
        ),
        ChainDefinition(
            name="汽车",
            proxy_symbol="516110.SH",
            stocks=[
                ChainStock("002594.SZ", "比亚迪", "汽车", "整车"),
                ChainStock("601633.SH", "长城汽车", "汽车", "整车"),
                ChainStock("002050.SZ", "三花智控", "汽车", "热管理"),
                ChainStock("300750.SZ", "宁德时代", "汽车", "动力电池"),
            ],
        ),
        ChainDefinition(
            name="通信AI",
            proxy_symbol="159695.SZ",
            stocks=[
                ChainStock("000063.SZ", "中兴通讯", "通信AI", "设备"),
                ChainStock("300308.SZ", "中际旭创", "通信AI", "光模块"),
                ChainStock("300502.SZ", "新易盛", "通信AI", "光模块"),
                ChainStock("601138.SH", "工业富联", "通信AI", "服务器"),
            ],
        ),
        ChainDefinition(
            name="电力",
            proxy_symbol="561560.SH",
            stocks=[
                ChainStock("600900.SH", "长江电力", "电力", "水电"),
                ChainStock("600886.SH", "国投电力", "电力", "水电"),
                ChainStock("600011.SH", "华能国际", "电力", "火电"),
                ChainStock("003816.SZ", "中国广核", "电力", "核电"),
            ],
        ),
    ]


def _ensure_ohlcv(bars: pd.DataFrame) -> pd.DataFrame:
    """补齐回测引擎需要的 OHLCV 字段。"""
    result = bars.copy()
    if "close" not in result.columns:
        raise ValueError("K线必须包含 close 列")
    for column in ["open", "high", "low"]:
        if column not in result.columns:
            result[column] = result["close"]
    if "volume" not in result.columns:
        result["volume"] = 0
    return result[["open", "high", "low", "close", "volume"]]


def _run_one_strategy(
    label: str,
    strategy: ChainStockSelectionStrategy,
    stock_bars: Dict[str, pd.DataFrame],
    market_bars: pd.DataFrame,
    initial_capital: float,
) -> dict:
    """执行单个产业链选股策略并汇总绩效。"""
    data_manager = DataManager()
    for symbol, bars in stock_bars.items():
        data_manager.load_data(symbol, _ensure_ohlcv(bars))
    data_manager.load_data("市场基线", _ensure_ohlcv(market_bars))

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
        benchmark_name="上证指数",
    )
    return {
        "方案": label,
        "策略": strategy.name,
        "总收益率": float(summary["总收益率"]),
        "年化收益率": float(summary["年化收益率"]),
        "最大回撤": float(summary["最大回撤"]),
        "夏普比率": float(summary["夏普比率"]),
        "交易次数": int(summary["交易次数"]),
        "基线收益率": float(benchmark["基线总收益率"]),
        "超额收益率": float(benchmark["超额收益率"]),
    }


def run_chain_selection_comparison(
    chains: List[ChainDefinition],
    stock_bars: Dict[str, pd.DataFrame],
    market_bars: pd.DataFrame,
    initial_capital: float = INITIAL_CAPITAL,
) -> pd.DataFrame:
    """运行 A/B/C 三种产业链选股方案并返回对比表。"""
    common_params = {
        "chains": chains,
        "top_n": 5,
        "rebalance_frequency": 5,
        "momentum_windows": [60, 120],
        "chain_momentum_window": 60,
        "chain_gate_symbol": "市场基线",
    }
    strategies = [
        ("A", ChainStockSelectionStrategy(
            **common_params,
            mode="single_chain",
            target_chain="半导体",
        )),
        ("B", ChainStockSelectionStrategy(**common_params, mode="multi_chain")),
        ("C", ChainStockSelectionStrategy(**common_params, mode="whole_pool")),
    ]
    rows = [
        _run_one_strategy(label, strategy, stock_bars, market_bars, initial_capital)
        for label, strategy in strategies
    ]
    return pd.DataFrame(rows)


def format_chain_selection_result(result: pd.DataFrame) -> str:
    """格式化 ABC 对比结果。"""
    display = result.copy()
    for column in ["总收益率", "年化收益率", "最大回撤", "基线收益率", "超额收益率"]:
        display[column] = display[column].map(lambda value: f"{value:.2%}")
    display["夏普比率"] = display["夏普比率"].map(lambda value: f"{value:.2f}")
    return display.to_string(index=False)


def _tencent_code(symbol: str) -> str:
    """将带交易所后缀的 A 股代码转换为腾讯代码。"""
    code, exchange = symbol.split(".")
    prefix = "sh" if exchange == "SH" else "sz"
    return f"{prefix}{code}"


def parse_tencent_stock_payload(payload: dict, tencent_code: str) -> pd.DataFrame:
    """解析腾讯个股/ETF K线，兼容 day 和 qfqday 两种返回字段。"""
    symbol_payload = (payload.get("data") or {}).get(tencent_code, {})
    raw_klines = symbol_payload.get("qfqday") or symbol_payload.get("day") or []
    return parse_tencent_klines(raw_klines)


def _fetch_tencent_stock_klines_remote(symbol: str, fetch_start: date, fetch_end: date) -> pd.DataFrame:
    """直接调用腾讯个股或 ETF 日 K 接口。"""
    tencent_code = _tencent_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,,,2000,qfq"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    df = parse_tencent_stock_payload(payload, tencent_code)
    return df[(df.index.date >= fetch_start) & (df.index.date <= fetch_end)]


def fetch_tencent_stock_klines(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
    cache_path=DEFAULT_CACHE_PATH,
) -> pd.DataFrame:
    """拉取腾讯个股日 K，并优先使用本地 SQLite 缓存。"""
    cache = MarketDataCache(cache_path)
    try:
        return load_or_fetch_ohlcv(
            cache=cache,
            provider=TENCENT_PROVIDER,
            symbol=symbol,
            frequency=FREQUENCY,
            adjust=ADJUST,
            start_date=fetch_start,
            end_date=fetch_end,
            fetcher=lambda start, end: _fetch_tencent_stock_klines_remote(symbol, start, end),
            max_fetch_days=2000,
        )
    finally:
        cache.close()


def _chain_symbols(chains: Iterable[ChainDefinition]) -> List[str]:
    """收集股票和产业链代理标的，保持顺序去重。"""
    symbols: List[str] = []
    for chain in chains:
        symbols.append(chain.proxy_symbol)
        symbols.extend(stock.symbol for stock in chain.stocks)
    return list(dict.fromkeys(symbols))


def build_real_chain_inputs(fetch_start: date, fetch_end: date) -> tuple[List[ChainDefinition], Dict[str, pd.DataFrame], pd.DataFrame]:
    """拉取真实产业链股票池和上证基线行情。"""
    chains = build_default_chain_definitions()
    stock_bars = {
        symbol: fetch_tencent_stock_klines(symbol, fetch_start, fetch_end)
        for symbol in _chain_symbols(chains)
    }
    market_bars = fetch_tencent_index_klines(SYMBOL, fetch_start=fetch_start, fetch_end=fetch_end)
    return chains, stock_bars, market_bars


def build_demo_chain_inputs() -> tuple[List[ChainDefinition], Dict[str, pd.DataFrame], pd.DataFrame]:
    """构造可离线运行的产业链选股样例。"""
    chains = build_default_chain_definitions()[:2]
    dates = pd.date_range(start="2023-01-01", periods=180, freq="D")

    def bars(start: float, step: float) -> pd.DataFrame:
        closes = [start + i * step for i in range(len(dates))]
        return pd.DataFrame({"close": closes, "volume": [1000000] * len(dates)}, index=dates)

    stock_bars = {
        "159995.SZ": bars(100, 0.12),
        "516110.SH": bars(100, 0.2),
        "688012.SH": bars(100, 0.35),
        "002371.SZ": bars(100, 0.1),
        "688008.SH": bars(100, 0.25),
        "603986.SH": bars(100, 0.08),
        "600584.SH": bars(100, 0.18),
        "002156.SZ": bars(100, 0.14),
        "002594.SZ": bars(100, 0.28),
        "601633.SH": bars(100, 0.16),
        "002050.SZ": bars(100, 0.2),
        "300750.SZ": bars(100, 0.22),
    }
    market_bars = bars(100, 0.15)
    return chains, stock_bars, market_bars


def main() -> None:
    """命令行入口，默认回测最近两年真实数据。"""
    parser = argparse.ArgumentParser(description="产业链选股 ABC 对比回测")
    parser.add_argument("--days", type=int, default=730, help="回测自然日长度，默认730")
    parser.add_argument("--demo", action="store_true", help="使用离线样例数据")
    args = parser.parse_args()

    if args.demo:
        chains, stock_bars, market_bars = build_demo_chain_inputs()
        print("产业链选股 ABC 对比，离线样例数据")
    else:
        fetch_end = date.today()
        fetch_start = fetch_end - timedelta(days=args.days)
        chains, stock_bars, market_bars = build_real_chain_inputs(fetch_start, fetch_end)
        print(f"产业链选股 ABC 对比，区间 {fetch_start} 至 {fetch_end}")

    result = run_chain_selection_comparison(chains, stock_bars, market_bars)
    print(format_chain_selection_result(result))


if __name__ == "__main__":
    main()
