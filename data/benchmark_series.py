"""生产回测使用的基准历史与增量拼接门面。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_adjusted_fund_curve(
    history_path: str | Path,
    increment_path: str | Path,
    symbol: str,
    *,
    end_date: str | None = None,
) -> pd.Series:
    """拼接基金历史库与增量库，增量同日记录覆盖历史记录。"""
    history = _load_history(Path(history_path), symbol, end_date)
    increment = _load_increment(Path(increment_path), symbol, end_date)
    pieces = [series for series in [history, increment] if not series.empty]
    if not pieces:
        return pd.Series(dtype=float)
    raw = pd.concat(pieces).sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    return raw / float(raw.iloc[0])


def _load_history(path: Path, symbol: str, end_date: str | None) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    import duckdb

    where = "WHERE ts_code = ?"
    parameters: list[str] = [symbol]
    if end_date:
        where += " AND trade_date <= ?"
        parameters.append(_normalize_date(end_date))
    with duckdb.connect(str(path), read_only=True) as connection:
        frame = connection.execute(
            f"""
            SELECT trade_date, close * adj_factor AS adjusted_close
            FROM etf_lof_reits_daily_adj
            {where}
            ORDER BY trade_date
            """,
            parameters,
        ).fetchdf()
    return _to_series(frame)


def _load_increment(path: Path, symbol: str, end_date: str | None) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    import duckdb

    where = "WHERE d.ts_code = ?"
    parameters: list[str] = [symbol]
    if end_date:
        where += " AND d.trade_date <= ?"
        parameters.append(_normalize_date(end_date))
    with duckdb.connect(str(path), read_only=True) as connection:
        frame = connection.execute(
            f"""
            SELECT d.trade_date, d.close * a.adj_factor AS adjusted_close
            FROM fund_daily d
            JOIN fund_adj a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            {where}
            ORDER BY d.trade_date
            """,
            parameters,
        ).fetchdf()
    return _to_series(frame)


def _to_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    index = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    return pd.Series(frame["adjusted_close"].astype(float).values, index=index).sort_index()


def _normalize_date(value: str) -> str:
    normalized = str(value).replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid date: {value}")
    return normalized
