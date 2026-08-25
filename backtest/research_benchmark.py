"""
研究基准工具。

仅使用 DuckDB 中已有的沪深300指数或 ETF 行情；若本地库没有相关数据，
返回空基准，避免引入新数据源或使用失真的代理基准。
"""

from __future__ import annotations

import pandas as pd

from data.fund_duckdb_source import DuckDBFundDataSource


HS300_CANDIDATES = ["000300.SH", "399300.SZ", "510300.SH", "159919.SZ"]
HS300_ETF_PREFERRED = ["510300.SH", "159919.SZ"]


def load_hs300_benchmark(
    con,
    start_date: str,
    fund_daily_path: str | None = None,
    fund_basic_path: str | None = None,
) -> tuple[pd.Series, str]:
    """读取沪深300参考基准，优先指数，其次本地沪深300 ETF。"""
    # 多取前 10 个自然日，确保年度收益能拿到上一年最后一个交易日。
    fetch_start = (pd.Timestamp(start_date) - pd.Timedelta(days=10)).strftime("%Y%m%d")
    curve, label = load_hs300_or_proxy(con, fetch_start)
    if not curve.empty or not fund_daily_path or not fund_basic_path:
        return curve, label
    fund_source = DuckDBFundDataSource(fund_daily_path, fund_basic_path)
    basic = fund_source.get_fund_basic()
    if basic.empty or "index_code" not in basic.columns:
        return curve, label
    hs300 = basic[basic["index_code"].fillna("").astype(str).eq("000300.SH")].copy()
    if hs300.empty:
        return curve, label
    hs300["priority"] = hs300["ts_code"].apply(lambda code: HS300_ETF_PREFERRED.index(code) if code in HS300_ETF_PREFERRED else 99)
    hs300 = hs300.sort_values(["priority", "list_date", "ts_code"])
    for symbol in hs300["ts_code"].tolist():
        bars = fund_source.get_daily_bars(symbol, fetch_start, None)
        if not bars.empty:
            # ETF 分红会改变复权因子，基准必须使用复权收盘价，否则低估含分红收益。
            close = bars["close"].astype(float) * bars["adj_factor"].astype(float)
            return close / close.iloc[0], f"HS300_ETF:{symbol}"
    return curve, label


def load_hs300_or_proxy(con, start_date: str) -> tuple[pd.Series, str]:
    """读取沪深300基准；本地缺失时返回空序列和缺失标签。"""
    for symbol in HS300_CANDIDATES:
        frame = con.execute(
            """
            SELECT trade_date, close_qfq AS close
            FROM daily_adj_cache
            WHERE ts_code = ? AND trade_date >= ?
            ORDER BY trade_date
            """,
            [symbol, start_date],
        ).fetchdf()
        if not frame.empty:
            return _close_to_curve(frame), symbol
    return pd.Series(dtype="float64"), "HS300_UNAVAILABLE_IN_DUCKDB"


def benchmark_metrics(curve: pd.Series) -> dict[str, float]:
    """计算基准收益和回撤。"""
    if curve.empty:
        return {"benchmark_return": 0.0, "benchmark_drawdown": 0.0}
    running_max = curve.expanding().max()
    return {
        "benchmark_return": float(curve.iloc[-1] / curve.iloc[0] - 1),
        "benchmark_drawdown": float(((curve - running_max) / running_max).min()),
    }


def align_benchmark_return(strategy_curve: pd.Series, benchmark_curve: pd.Series) -> float:
    """对齐策略日期后计算同期基准收益。"""
    aligned = benchmark_curve.reindex(strategy_curve.index).ffill().dropna()
    if aligned.empty:
        return float("nan")
    return float(aligned.iloc[-1] / aligned.iloc[0] - 1)


def _close_to_curve(frame: pd.DataFrame) -> pd.Series:
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    close = frame.set_index("date")["close"].astype(float)
    return close / close.iloc[0]
