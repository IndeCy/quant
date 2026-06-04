"""
行业代理行情数据源

使用行业 ETF 作为行业轮动策略的可交易代理标的，行情默认走腾讯日 K 并写入本地缓存。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Dict
from urllib.request import Request, urlopen

import pandas as pd

from backtest.cache import DEFAULT_CACHE_PATH, MarketDataCache, load_or_fetch_ohlcv
from examples.shanghai_index_ma_backtest import ADJUST, FREQUENCY, TENCENT_PROVIDER, parse_tencent_klines


@dataclass(frozen=True)
class IndustryProxyETF:
    """行业 ETF 代理配置"""

    industry: str
    symbol: str
    name: str
    description: str


INDUSTRY_PROXY_ETFS: Dict[str, IndustryProxyETF] = {
    "电力": IndustryProxyETF("电力", "561560.SH", "电力ETF", "电力与公用事业方向代理"),
    "半导体": IndustryProxyETF("半导体", "159995.SZ", "芯片ETF", "半导体芯片方向代理"),
    "通信设备": IndustryProxyETF("通信设备", "159695.SZ", "通信ETF", "通信与光通信方向代理"),
    "设备制造": IndustryProxyETF("设备制造", "562500.SH", "机器人ETF", "自动化设备与机器人方向代理"),
    "汽车": IndustryProxyETF("汽车", "516110.SH", "汽车ETF", "汽车整车与零部件方向代理"),
    "消费电子": IndustryProxyETF("消费电子", "159732.SZ", "消费电子ETF", "消费电子硬件方向代理"),
    "有色金属": IndustryProxyETF("有色金属", "159980.SZ", "有色ETF", "有色与小金属方向代理"),
    "煤炭": IndustryProxyETF("煤炭", "159930.SZ", "能源ETF", "煤炭与传统能源方向代理"),
    "银行": IndustryProxyETF("银行", "159887.SZ", "银行ETF", "银行与金融防守方向代理"),
    "红利低波": IndustryProxyETF("红利低波", "159549.SZ", "红利低波ETF", "高股息低波防守方向代理"),
    "黄金": IndustryProxyETF("黄金", "517520.SH", "黄金股ETF", "黄金和贵金属避险方向代理"),
    "医药": IndustryProxyETF("医药", "159929.SZ", "医药ETF", "医药防御方向代理"),
    "运营商": IndustryProxyETF("运营商", "560680.SH", "电信ETF", "运营商高股息方向代理"),
}


def get_default_industry_proxy_symbols() -> Dict[str, str]:
    """返回行业名称到 ETF 代码的默认映射。"""
    return {industry: proxy.symbol for industry, proxy in INDUSTRY_PROXY_ETFS.items()}


def tencent_security_code(symbol: str) -> str:
    """将证券代码转换为腾讯接口代码，如 512480.SH -> sh512480。"""
    code, exchange = symbol.split(".")
    if exchange == "SH":
        return f"sh{code}"
    if exchange == "SZ":
        return f"sz{code}"
    raise ValueError(f"暂不支持的交易所后缀: {symbol}")


def _fetch_tencent_security_klines_remote(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
) -> pd.DataFrame:
    """直接调用腾讯日 K 接口拉取 ETF 或指数行情。"""
    tencent_code = tencent_security_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,,,2000,qfq"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    raw_klines = (payload.get("data") or {}).get(tencent_code, {}).get("day") or []
    df = parse_tencent_klines(raw_klines)
    return df[(df.index.date >= fetch_start) & (df.index.date <= fetch_end)]


def fetch_industry_proxy_klines(
    symbol: str,
    fetch_start: date,
    fetch_end: date,
    use_cache: bool = True,
    cache_path=DEFAULT_CACHE_PATH,
) -> pd.DataFrame:
    """拉取行业代理 ETF 日 K，默认优先读取本地时序缓存。"""
    if not use_cache:
        return _fetch_tencent_security_klines_remote(symbol, fetch_start, fetch_end)

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
            fetcher=lambda start, end: _fetch_tencent_security_klines_remote(symbol, start, end),
            max_fetch_days=2000,
        )
    finally:
        cache.close()


def fetch_default_industry_proxy_bars(
    fetch_start: date,
    fetch_end: date,
    use_cache: bool = True,
    cache_path=DEFAULT_CACHE_PATH,
) -> Dict[str, pd.DataFrame]:
    """拉取默认行业代理池 K 线，返回行业名称到行情表的映射。"""
    return {
        industry: fetch_industry_proxy_klines(proxy.symbol, fetch_start, fetch_end, use_cache, cache_path)
        for industry, proxy in INDUSTRY_PROXY_ETFS.items()
    }
