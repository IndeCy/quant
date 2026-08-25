"""基金组合研究使用的统一 qfq 日线面板。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from data.cleaning import clean_daily_bars


@dataclass(frozen=True)
class FundPortfolioPanel:
    """包含可成交日线、复权收盘价、交易日历和覆盖诊断。"""

    bars: pd.DataFrame
    adjusted_close: pd.DataFrame
    calendar: list[pd.Timestamp]
    coverage: list[dict[str, object]]
    latest_common_date: str


def load_fund_portfolio_panel(
    history_path: str | Path,
    increment_path: str | Path,
    symbols: list[str],
    *,
    start_date: str,
    end_date: str,
) -> FundPortfolioPanel:
    """拼接历史与增量基金行情，并按数据截止日生成 qfq 面板。"""
    normalized_symbols = list(dict.fromkeys(str(item) for item in symbols))
    if not normalized_symbols:
        raise ValueError("symbols cannot be empty")
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    if start > end:
        raise ValueError("start_date cannot be later than end_date")

    history = _load_history(Path(history_path), normalized_symbols, start, end)
    increment = _load_increment(Path(increment_path), normalized_symbols, start, end)
    frames = [item for item in [history, increment] if not item.empty]
    if not frames:
        raise ValueError("基金历史库和增量库均没有目标资产数据")
    raw = pd.concat(frames, ignore_index=True)
    raw = (
        raw.sort_values(["symbol", "trade_date", "source_priority"])
        .drop_duplicates(["symbol", "trade_date"], keep="last")
        .reset_index(drop=True)
    )
    missing = sorted(set(normalized_symbols) - set(raw["symbol"].astype(str)))
    if missing:
        raise ValueError(f"基金资产缺少行情: {missing}")
    _validate_raw_prices(raw)

    coverage = _build_coverage(raw, normalized_symbols)
    latest_common = min(str(item["end_date"]) for item in coverage)
    raw = raw[raw["trade_date"].le(latest_common)].copy()
    raw = _apply_qfq(raw)
    bars = _clean_panel(raw)
    close = (
        bars.reset_index()
        .pivot(index="date", columns="symbol", values="close")
        .sort_index()
        .dropna(subset=normalized_symbols)
    )
    if close.empty:
        raise ValueError("目标基金没有共同可交易日期")
    common_dates = set(close.index)
    bars = bars[bars.index.get_level_values("date").isin(common_dates)].sort_index()
    return FundPortfolioPanel(
        bars=bars,
        adjusted_close=close[normalized_symbols],
        calendar=list(close.index),
        coverage=coverage,
        latest_common_date=latest_common,
    )


def _load_history(
    path: Path,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """读取本地基金历史基线。"""
    if not path.exists():
        return _empty_raw()
    placeholders = ",".join("?" for _ in symbols)
    with duckdb.connect(str(path), read_only=True) as connection:
        return connection.execute(
            f"""
            SELECT
                trade_date,
                ts_code AS symbol,
                open,
                high,
                low,
                close,
                vol AS volume,
                amount,
                adj_factor,
                0 AS source_priority
            FROM etf_lof_reits_daily_adj
            WHERE ts_code IN ({placeholders})
              AND trade_date BETWEEN ? AND ?
            ORDER BY ts_code, trade_date
            """,
            [*symbols, start_date, end_date],
        ).fetchdf()


def _load_increment(
    path: Path,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """读取 Tushare 基金增量，同日数据覆盖历史基线。"""
    if not path.exists():
        return _empty_raw()
    placeholders = ",".join("?" for _ in symbols)
    with duckdb.connect(str(path), read_only=True) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if not {"fund_daily", "fund_adj"}.issubset(tables):
            return _empty_raw()
        return connection.execute(
            f"""
            SELECT
                d.trade_date,
                d.ts_code AS symbol,
                d.open,
                d.high,
                d.low,
                d.close,
                d.vol AS volume,
                d.amount,
                a.adj_factor,
                1 AS source_priority
            FROM fund_daily d
            JOIN fund_adj a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.ts_code IN ({placeholders})
              AND d.trade_date BETWEEN ? AND ?
            ORDER BY d.ts_code, d.trade_date
            """,
            [*symbols, start_date, end_date],
        ).fetchdf()


def _validate_raw_prices(frame: pd.DataFrame) -> None:
    """复权因子或价格异常时直接阻止研究。"""
    numeric = ["open", "high", "low", "close", "adj_factor"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    invalid = frame[numeric].isna().any(axis=1) | frame[numeric].le(0).any(axis=1)
    if invalid.any():
        rows = frame.loc[invalid, ["trade_date", "symbol"]].head(5).to_dict("records")
        raise ValueError(f"基金价格或复权因子异常: {rows}")


def _build_coverage(
    frame: pd.DataFrame,
    symbols: list[str],
) -> list[dict[str, object]]:
    """记录每个资产的起止日期和样本数。"""
    result: list[dict[str, object]] = []
    for symbol in symbols:
        values = frame[frame["symbol"].astype(str).eq(symbol)]
        result.append(
            {
                "symbol": symbol,
                "start_date": str(values["trade_date"].min()),
                "end_date": str(values["trade_date"].max()),
                "row_count": int(len(values)),
            }
        )
    return result


def _apply_qfq(frame: pd.DataFrame) -> pd.DataFrame:
    """按本次截止日最后复权因子缩放 OHLC，避免读取未来因子。"""
    result = frame.copy()
    last_factor = (
        result.sort_values("trade_date")
        .groupby("symbol", sort=False)["adj_factor"]
        .last()
    )
    result["last_adj_factor"] = result["symbol"].map(last_factor)
    for column in ["open", "high", "low", "close"]:
        result[column] = (
            result[column].astype(float)
            * result["adj_factor"].astype(float)
            / result["last_adj_factor"].astype(float)
        )
    return result


def _clean_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """逐资产进入统一 schema，并转换为回测使用的双层索引。"""
    cleaned: list[pd.DataFrame] = []
    for symbol, group in frame.groupby("symbol", sort=True):
        values = group[
            [
                "trade_date",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "adj_factor",
            ]
        ].copy()
        values["code"] = str(symbol)
        values["is_suspended"] = (
            pd.to_numeric(values["volume"], errors="coerce").fillna(0).le(0)
        )
        # 基线库没有可靠 ETF 涨跌停标记，研究报告会显式披露该限制。
        values["limit_up"] = False
        values["limit_down"] = False
        values["limit_status_available"] = False
        item = clean_daily_bars(values, symbol=str(symbol)).reset_index()
        item = item.rename(columns={"trade_date": "date"})
        cleaned.append(item)
    output = pd.concat(cleaned, ignore_index=True)
    if output["has_missing_price"].any() or output["has_invalid_price"].any():
        raise ValueError("基金统一 schema 清洗后仍存在无效价格")
    return output.set_index(["date", "symbol"]).sort_index()


def _empty_raw() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adj_factor",
            "source_priority",
        ]
    )


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
