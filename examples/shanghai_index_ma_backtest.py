"""
上证指数最近一个月双均线策略回测示例

说明：
- 标的使用上证指数 000001.SH 的指数点位数据。
- 指数本身不能像股票一样直接买卖，本示例用于验证双均线择时信号和净值模拟。
- 数据来自东方财富指数日 K 接口，抓取时会额外保留预热区间，避免 20 日均线在回测初期失真。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from typing import Iterable, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.cache import DEFAULT_CACHE_PATH, MarketDataCache, load_or_fetch_ohlcv
from backtest.data import DataManager
from backtest.engine import BacktestEngine
from backtest.strategies import MovingAverageCrossStrategy


SYMBOL = "000001.SH"
SYMBOL_NAME = "上证指数"
SHORT_WINDOW = 5
LONG_WINDOW = 20
INITIAL_CAPITAL = 1_000_000.0
EASTMONEY_PROVIDER = "eastmoney"
TENCENT_PROVIDER = "tencent"
FREQUENCY = "1d"
ADJUST = "none"


def build_recent_month_window(
    today: date | None = None,
    run_days: int = 31,
    warmup_days: int = 90,
) -> Tuple[date, date, date]:
    """
    构建数据抓取窗口和实际回测窗口。

    Args:
        today: 当前日期，默认取系统日期。
        run_days: 实际回测最近天数，默认最近31个自然日。
        warmup_days: 均线预热天数，保证长均线有足够历史样本。

    Returns:
        (fetch_start, run_start, run_end): 数据抓取开始、回测开始、回测结束日期。
    """
    run_end = today or date.today()
    run_start = run_end - timedelta(days=run_days)
    fetch_start = run_start - timedelta(days=warmup_days)
    return fetch_start, run_start, run_end


def parse_eastmoney_klines(raw_klines: Iterable[str]) -> pd.DataFrame:
    """
    将东方财富 K 线字符串转换为回测系统标准 DataFrame。

    东财字段顺序为：日期、开盘、收盘、最高、最低、成交量、成交额等。
    回测引擎要求字段顺序为 open/high/low/close/volume，可额外保留 amount。
    """
    records = []
    for line in raw_klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue

        # 指数点位字段转成数值，避免后续均线和收益计算走字符串比较。
        records.append(
            {
                "date": pd.to_datetime(parts[0]),
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
            }
        )

    if not records:
        raise ValueError("东方财富未返回有效K线数据")

    df = pd.DataFrame(records).set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume", "amount"]]


def parse_tencent_klines(raw_klines: Iterable[list[str]]) -> pd.DataFrame:
    """
    将腾讯 K 线数组转换为回测系统标准 DataFrame。

    腾讯字段顺序为：日期、开盘、收盘、最高、最低、成交量。
    指数场景下腾讯接口不返回成交额，这里 amount 统一填 0。
    """
    records = []
    for item in raw_klines:
        if len(item) < 6:
            continue

        # 腾讯返回的是字符串数组，统一转为数值后进入回测引擎。
        records.append(
            {
                "date": pd.to_datetime(item[0]),
                "open": float(item[1]),
                "close": float(item[2]),
                "high": float(item[3]),
                "low": float(item[4]),
                "volume": float(item[5]),
                "amount": 0.0,
            }
        )

    if not records:
        raise ValueError("腾讯未返回有效K线数据")

    df = pd.DataFrame(records).set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume", "amount"]]


def _eastmoney_index_secid(symbol: str) -> str:
    """
    将指数代码转换为东方财富 secid。

    上交所指数使用市场前缀 1，深交所指数使用市场前缀 0。
    """
    code, exchange = symbol.split(".")
    if exchange == "SH":
        return f"1.{code}"
    if exchange == "SZ":
        return f"0.{code}"
    raise ValueError(f"暂不支持的指数代码: {symbol}")


def _tencent_index_code(symbol: str) -> str:
    """将指数代码转换为腾讯接口代码，如 000852.SH -> sh000852。"""
    code, exchange = symbol.split(".")
    if exchange == "SH":
        return f"sh{code}"
    if exchange == "SZ":
        return f"sz{code}"
    raise ValueError(f"暂不支持的指数代码: {symbol}")


def _fetch_eastmoney_index_klines_remote(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
) -> pd.DataFrame:
    """
    直接调用东方财富指数日 K 接口。

    本函数只负责远程请求，不读写缓存，便于缓存层按缺口精确补拉。
    """
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": _eastmoney_index_secid(symbol),
        "klt": "101",
        "fqt": "0",
        "beg": fetch_start.strftime("%Y%m%d"),
        "end": fetch_end.strftime("%Y%m%d"),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}

    query_url = f"{url}?{urlencode(params, safe=',')}"
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = Request(query_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Connection": "close",
                **headers,
            })
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                # 行情接口偶发断连时稍等后重试，避免一次网络抖动中断回测。
                time.sleep(attempt)
    else:
        try:
            # 东财偶发拒绝 Python HTTP 连接时，使用 curl 作为兜底抓取路径。
            result = subprocess.run(
                [
                    "curl",
                    "-L",
                    "--retry",
                    "5",
                    "--retry-all-errors",
                    "--retry-delay",
                    "2",
                    "--connect-timeout",
                    "10",
                    "--max-time",
                    "20",
                    "-A",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "-e",
                    "https://quote.eastmoney.com/",
                    query_url,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
        except Exception as exc:
            raise RuntimeError(f"获取上证指数K线失败，已重试3次: {last_error}") from exc

    klines = (payload.get("data") or {}).get("klines") or []
    return parse_eastmoney_klines(klines)


def fetch_eastmoney_index_klines(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
    use_cache: bool = True,
    cache_path=DEFAULT_CACHE_PATH,
) -> pd.DataFrame:
    """
    拉取东方财富指数日 K 数据，默认启用本地 SQLite 时序缓存。

    缓存维度为 provider + symbol + frequency + adjust + trade_time。
    当目标区间已被覆盖时，直接从本地读取，不再请求外部接口。
    """
    if not use_cache:
        return _fetch_eastmoney_index_klines_remote(symbol, fetch_start, fetch_end)

    cache = MarketDataCache(cache_path)
    try:
        return load_or_fetch_ohlcv(
            cache=cache,
            provider=EASTMONEY_PROVIDER,
            symbol=symbol,
            frequency=FREQUENCY,
            adjust=ADJUST,
            start_date=fetch_start,
            end_date=fetch_end,
            fetcher=lambda start, end: _fetch_eastmoney_index_klines_remote(symbol, start, end),
        )
    finally:
        cache.close()


def _fetch_tencent_index_klines_remote(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
) -> pd.DataFrame:
    """
    直接调用腾讯指数日 K 接口。

    腾讯接口按返回根数控制，这里使用较大的 lmt 拉取最近历史，再按目标日期裁剪。
    """
    tencent_code = _tencent_index_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,,,2000,qfq"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    raw_klines = (payload.get("data") or {}).get(tencent_code, {}).get("day") or []
    df = parse_tencent_klines(raw_klines)
    return df[(df.index.date >= fetch_start) & (df.index.date <= fetch_end)]


def fetch_tencent_index_klines(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
    use_cache: bool = True,
    cache_path=DEFAULT_CACHE_PATH,
) -> pd.DataFrame:
    """
    拉取腾讯指数日 K 数据，默认启用本地 SQLite 时序缓存。

    provider 使用 tencent，和 eastmoney 缓存彼此隔离，避免不同数据源混用。
    """
    if not use_cache:
        return _fetch_tencent_index_klines_remote(symbol, fetch_start, fetch_end)

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
            fetcher=lambda start, end: _fetch_tencent_index_klines_remote(symbol, start, end),
            max_fetch_days=2000,
        )
    finally:
        cache.close()


def fetch_shanghai_index_klines(
    fetch_start: date,
    fetch_end: date,
    use_cache: bool = True,
    cache_path=DEFAULT_CACHE_PATH,
) -> pd.DataFrame:
    """拉取上证指数日 K 数据，默认优先使用本地缓存。"""
    return fetch_eastmoney_index_klines(
        SYMBOL,
        fetch_start,
        fetch_end,
        use_cache=use_cache,
        cache_path=cache_path,
    )


def run_backtest() -> tuple[pd.DataFrame, BacktestEngine, PerformanceAnalyzer]:
    """执行最近一个月上证指数双均线回测。"""
    from backtest.analysis import PerformanceAnalyzer

    fetch_start, run_start, run_end = build_recent_month_window()
    print(f"{SYMBOL_NAME}({SYMBOL}) 双均线回测")
    print(f"数据抓取区间: {fetch_start} ~ {run_end}")
    print(f"实际回测区间: {run_start} ~ {run_end}")
    print(f"策略参数: MA{SHORT_WINDOW}/MA{LONG_WINDOW}")

    df = fetch_shanghai_index_klines(fetch_start, run_end)
    if df[df.index >= pd.Timestamp(run_start)].empty:
        raise ValueError("最近一个月没有可回测的上证指数数据")

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
    return results, engine, analyzer


def main() -> None:
    """命令行入口：打印回测绩效和交易明细。"""
    results, engine, analyzer = run_backtest()
    analyzer.print_summary()

    if engine.trades:
        trades_df = pd.DataFrame(engine.trades)
        print("交易明细:")
        print(trades_df.to_string(index=False))
    else:
        print("最近一个月未触发双均线交易信号。")

    print("最近5个交易日资产:")
    print(results.tail().to_string())


if __name__ == "__main__":
    main()
