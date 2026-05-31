"""
A股数据获取模块 (A-share Data Fetcher)

整合 simonlin1212/a-stock-data (V3.2) 的数据获取能力，覆盖：
  行情层  — mootdx K线/实时报价 + 腾讯财经 PE/PB/市值
  资金层  — 东财个股资金流向（分钟级）
  信号层  — 东财行业板块涨跌
  基础数据 — 东财个股基本信息（行业/总股本/流通股/市值/上市日期）

依赖：mootdx requests pandas

数据源优先级（源自 a-stock-data V3.2）：
  1. mootdx（通达信 TCP，不封 IP）— K线/五档/逐笔/财务
  2. 腾讯财经（HTTP，不封 IP）    — 实时价/PE/PB/市值/换手率
  3. 东财（HTTP，有风控）          — 资金流/行业/个股信息，统一走 em_get() 限流
"""

import random
import time
import urllib.request
from typing import Optional

import pandas as pd
import requests

# ── 通用 User-Agent ────────────────────────────────────────────────────────────
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 东财防封：全局节流 + 会话复用 ─────────────────────────────────────────────
# 东财系 HTTP 接口有风控阈值（每秒 >5 次/并发 ≥10/1分 ≥200 次 → 临时封 IP）。
# 所有 eastmoney.com 请求一律走 em_get()：串行限流 + 随机抖动 + Keep-Alive 复用。
_EM_SESSION = requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
EM_MIN_INTERVAL: float = 1.0  # 两次东财请求最小间隔(秒)；批量任务建议调大到 1.5~2
_em_last_call: list[float] = [0.0]


def em_get(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。

    所有 eastmoney.com 接口都应通过本函数请求，避免高频被封 IP。
    节流间隔由模块级 EM_MIN_INTERVAL 控制，批量调用时可调大。
    """
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _EM_SESSION.get(
            url, params=params, headers=headers, timeout=timeout, **kwargs
        )
    finally:
        _em_last_call[0] = time.time()


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: 行情层
# ─────────────────────────────────────────────────────────────────────────────


def get_klines(
    symbol: str,
    category: int = 4,
    offset: int = 250,
) -> pd.DataFrame:
    """获取A股历史K线数据（通达信 mootdx，不封IP）。

    数据直接可用于 DataManager.load_data()，返回的 DataFrame 索引为日期。

    Args:
        symbol: 6位股票代码（如 '000001'、'688017'），无需交易所后缀。
        category: K线周期。
            4=日线（默认）、5=周线、6=月线、
            7=1分钟、8=5分钟、9=15分钟、10=30分钟、11=60分钟
        offset: 获取的K线数量，最大 800。默认 250（约1年日线）。

    Returns:
        DataFrame，列包含 [open, high, low, close, volume, amount]，
        索引为 DatetimeIndex（日期/时间）。

    Raises:
        ImportError: 未安装 mootdx 时抛出。
        RuntimeError: 获取数据失败时抛出。

    Example::

        from backtest.fetcher import get_klines
        from backtest.data import DataManager

        dm = DataManager()
        df = get_klines('000001', category=4, offset=250)
        dm.load_data('000001.SZ', df)
    """
    try:
        from mootdx.quotes import Quotes
    except ImportError as exc:
        raise ImportError(
            "mootdx 未安装，请执行: pip install mootdx"
        ) from exc

    client = Quotes.factory(market="std")
    raw = client.bars(symbol=symbol, category=category, offset=offset)

    if raw is None or (hasattr(raw, "__len__") and len(raw) == 0):
        raise RuntimeError(f"mootdx 未返回数据：symbol={symbol}")

    df = pd.DataFrame(raw) if not isinstance(raw, pd.DataFrame) else raw.copy()

    # mootdx 返回字段：open, close, high, low, vol, amount, datetime
    col_map = {"vol": "volume", "datetime": "date"}
    df = df.rename(columns=col_map)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # 保留标准列
    keep = [c for c in ["open", "high", "low", "close", "volume", "amount"] if c in df.columns]
    return df[keep]


def load_symbol(
    data_manager,
    symbol: str,
    category: int = 4,
    offset: int = 250,
) -> pd.DataFrame:
    """便捷函数：获取K线数据并直接加载进 DataManager。

    Args:
        data_manager: backtest.data.DataManager 实例。
        symbol: 6位股票代码（如 '000001'），无需交易所后缀。
        category: K线周期，同 get_klines()。
        offset: 获取的K线数量，同 get_klines()。

    Returns:
        加载后的 DataFrame。

    Example::

        from backtest.data import DataManager
        from backtest.fetcher import load_symbol

        dm = DataManager()
        load_symbol(dm, '000001')           # 自动推断交易所后缀
        load_symbol(dm, '688017')           # 科创板
        load_symbol(dm, '000001', offset=500)
    """
    df = get_klines(symbol, category=category, offset=offset)

    # 推断交易所后缀：6/9 开头→上交所(.SH)，8 开头→北交所(.BJ)，其他→深交所(.SZ)
    if symbol.startswith(("6", "9")):
        full_symbol = f"{symbol}.SH"
    elif symbol.startswith("8"):
        full_symbol = f"{symbol}.BJ"
    else:
        full_symbol = f"{symbol}.SZ"

    data_manager.load_data(full_symbol, df)
    return df


def get_realtime_quote(codes: list[str]) -> dict[str, dict]:
    """批量获取腾讯财经实时行情（不封IP）。

    涵盖：当前价、PE(TTM)、PB、总市值、流通市值、换手率、涨跌停价等。

    Args:
        codes: 6位股票代码列表，同时支持指数和ETF代码。
            示例：['688017', '000001', '300476']
            指数：['000001', '000300', '399006']（上证/沪深300/创业板指）
            ETF： ['510050', '510300']

    Returns:
        dict，键为6位代码，值为行情字段字典::

            {
              'name': '股票名称',
              'price': 当前价,
              'last_close': 昨收,
              'open': 今开,
              'change_amt': 涨跌额,
              'change_pct': 涨跌幅(%),
              'high': 最高,
              'low': 最低,
              'amount_wan': 成交额(万元),
              'turnover_pct': 换手率(%),
              'pe_ttm': PE(TTM),
              'pe_static': PE(静),
              'pb': PB(市净率),
              'mcap_yi': 总市值(亿元),
              'float_mcap_yi': 流通市值(亿元),
              'limit_up': 涨停价,
              'limit_down': 跌停价,
              'amplitude_pct': 振幅(%),
              'vol_ratio': 量比,
            }

    Example::

        from backtest.fetcher import get_realtime_quote

        quotes = get_realtime_quote(['688017', '000858'])
        for code, q in quotes.items():
            print(f"{q['name']}({code}): {q['price']}元  PE={q['pe_ttm']}  PB={q['pb']}")
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result: dict[str, dict] = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key_part = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key_part[2:]  # 去掉 sh/sz/bj 前缀

        def _f(idx: int) -> float:
            return float(vals[idx]) if vals[idx] else 0.0

        result[code] = {
            "name": vals[1],
            "price": _f(3),
            "last_close": _f(4),
            "open": _f(5),
            "change_amt": _f(31),
            "change_pct": _f(32),
            "high": _f(33),
            "low": _f(34),
            "amount_wan": _f(37),
            "turnover_pct": _f(38),
            "pe_ttm": _f(39),
            "amplitude_pct": _f(43),  # 注意：43=振幅%，不是PB
            "mcap_yi": _f(44),
            "float_mcap_yi": _f(45),
            "pb": _f(46),             # PB 在索引 46
            "limit_up": _f(47),
            "limit_down": _f(48),
            "vol_ratio": _f(49),
            "pe_static": _f(52),
        }
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 (部分): 信号层 — 行业板块
# ─────────────────────────────────────────────────────────────────────────────


def get_industry_sectors(page_size: int = 100) -> list[dict]:
    """获取东财行业板块涨跌排行（零鉴权，已内置限流）。

    Args:
        page_size: 返回的行业数量，默认 100（含全部主要行业）。

    Returns:
        行业列表，每项包含::

            {
              'name': 行业名称,
              'change_pct': 涨跌幅(%),
              'up_count': 上涨家数,
              'down_count': 下跌家数,
              'leader_name': 领涨股名称,
              'leader_code': 领涨股代码,
              'leader_change_pct': 领涨股涨跌幅(%),
            }

    Example::

        from backtest.fetcher import get_industry_sectors

        sectors = get_industry_sectors()
        top5 = sorted(sectors, key=lambda x: x['change_pct'], reverse=True)[:5]
        for s in top5:
            print(f"{s['name']}: {s['change_pct']:+.2f}%  ↑{s['up_count']} ↓{s['down_count']}")
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": str(page_size), "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:2+f:!50",
        "fields": "f1,f2,f3,f4,f8,f12,f14,f15,f16,f17,f18,f20,f21,f24,f25,f22,f33,f11,f62,f128,f136,f140,f141,f207,f208,f209,f222",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    r = em_get(url, params=params, headers=headers, timeout=15)
    d = r.json()
    items = (d.get("data") or {}).get("diff") or []

    result = []
    for item in items:
        result.append({
            "name": item.get("f14", ""),
            "change_pct": float(item.get("f3", 0) or 0),
            "up_count": int(item.get("f104", 0) or 0),
            "down_count": int(item.get("f105", 0) or 0),
            "leader_name": item.get("f128", ""),
            "leader_code": item.get("f140", ""),
            "leader_change_pct": float(item.get("f136", 0) or 0),
        })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4 (部分): 资金面 — 个股资金流向
# ─────────────────────────────────────────────────────────────────────────────


def get_fund_flow_minute(symbol: str) -> list[dict]:
    """获取个股当日分钟级资金流向（东财 push2，已内置限流）。

    Args:
        symbol: 6位股票代码（如 '000858'）。

    Returns:
        分钟级资金流列表，每项包含::

            {
              'time': 时间字符串,
              'main_net': 主力净流入(元),
              'small_net': 小单净流入(元),
              'mid_net': 中单净流入(元),
              'large_net': 大单净流入(元),
              'super_net': 超大单净流入(元),
            }

        注意：金额单位为**元**，非万元。

    Example::

        from backtest.fetcher import get_fund_flow_minute

        flows = get_fund_flow_minute('000858')
        if flows:
            last = flows[-1]
            signal = '流入' if last['main_net'] > 0 else '流出'
            print(f"主力净{signal}: {last['main_net'] / 1e4:.1f}万元")
            total = sum(r['main_net'] for r in flows)
            print(f"全天主力累计: {total / 1e4:.1f}万元")
    """
    secid = f"1.{symbol}" if symbol.startswith("6") else f"0.{symbol}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {
        "User-Agent": _UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as exc:
        print(f"[WARN] 资金流请求失败: {exc}")
        return []

    rows = []
    for line in (d.get("data") or {}).get("klines") or []:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "large_net": float(parts[4]),
                "super_net": float(parts[5]),
            })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Layer 6 (部分): 基础数据 — 东财个股基本信息
# ─────────────────────────────────────────────────────────────────────────────


def get_stock_info(symbol: str) -> dict:
    """获取个股基本信息（东财 push2，已内置限流）。

    返回行业、总股本、流通股、市值、上市日期等字段，适合做基本面筛选。

    Args:
        symbol: 6位股票代码（如 '600519'）。

    Returns:
        字典包含::

            {
              'name': 股票名称,
              'industry': 所属行业,
              'total_shares': 总股本(股),
              'float_shares': 流通股(股),
              'total_mcap': 总市值(元),
              'float_mcap': 流通市值(元),
              'list_date': 上市日期(字符串 YYYY-MM-DD),
              'price': 当前价,
              'pe_ttm': PE(TTM),
              'pb': PB,
            }

    Example::

        from backtest.fetcher import get_stock_info

        info = get_stock_info('600519')
        print(f"{info['name']} 行业:{info['industry']} 上市:{info['list_date']}")
        print(f"总市值:{info['total_mcap'] / 1e8:.1f}亿  PE:{info['pe_ttm']:.1f}  PB:{info['pb']:.2f}")
    """
    secid = f"1.{symbol}" if symbol.startswith("6") else f"0.{symbol}"
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields": (
            "f57,f58,f84,f85,f116,f117,f135,f136,f137,f138,"
            "f139,f140,f141,f142,f26,f37,f38,f39,f40,"
            "f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,"
            "f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,"
            "f63,f64,f65,f66,f67,f68,f69,f70,f71,f169,"
            "f170,f171,f161,f49,f171,f172,f191,f192,f173,f196,"
            "f97,f107,f111,f86,f88,f100,f168,f108,f238,f118"
        ),
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json().get("data") or {}
    except Exception as exc:
        print(f"[WARN] 个股信息请求失败: {exc}")
        return {}

    def _num(val, divisor: float = 1.0) -> float:
        try:
            return float(val) / divisor
        except (TypeError, ValueError):
            return 0.0

    list_date_raw = str(d.get("f26", "") or "")
    if len(list_date_raw) == 8:
        list_date = f"{list_date_raw[:4]}-{list_date_raw[4:6]}-{list_date_raw[6:]}"
    else:
        list_date = list_date_raw

    return {
        "name": d.get("f58", ""),
        "industry": d.get("f100", ""),
        "total_shares": _num(d.get("f84")),
        "float_shares": _num(d.get("f85")),
        "total_mcap": _num(d.get("f116")),
        "float_mcap": _num(d.get("f117")),
        "list_date": list_date,
        "price": _num(d.get("f43")) / 100,  # push2 价格单位为分，需除以100
        "pe_ttm": _num(d.get("f164")),
        "pb": _num(d.get("f167")),
    }
