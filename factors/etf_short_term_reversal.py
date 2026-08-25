"""ETF 周频短期反转横截面。"""

from __future__ import annotations

import pandas as pd


def calculate_weekly_reversal_states(
    adjusted_close: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    symbols: list[str],
    *,
    lookback_days: int = 5,
) -> pd.DataFrame:
    """只用信号日及以前价格计算5日收益并按从弱到强排序。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    normalized = list(dict.fromkeys(str(symbol) for symbol in symbols))
    missing = sorted(set(normalized) - set(adjusted_close.columns))
    if missing:
        raise ValueError(f"adjusted_close missing symbols: {missing}")
    close = adjusted_close[normalized].sort_index().astype(float)
    trailing = close / close.shift(lookback_days) - 1.0
    rows: list[dict[str, object]] = []
    for raw_date in signal_dates:
        date = pd.Timestamp(raw_date)
        if date not in trailing.index:
            continue
        daily = [
            {
                "signal_date": date.strftime("%Y%m%d"),
                "symbol": symbol,
                "return_5d": float(trailing.at[date, symbol]),
            }
            for symbol in normalized
            if pd.notna(trailing.at[date, symbol])
        ]
        ranked = sorted(
            daily,
            key=lambda item: (float(item["return_5d"]), str(item["symbol"])),
        )
        count = len(ranked)
        for rank, item in enumerate(ranked, start=1):
            rows.append(
                {
                    **item,
                    "reversal_rank": rank,
                    "momentum_rank": count - rank + 1,
                }
            )
    return pd.DataFrame(rows)


def build_ranked_targets(
    states: pd.DataFrame,
    *,
    top_n: int,
    rank_column: str,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """按预先指定排名列等权持有每周前三名。"""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if rank_column not in {"reversal_rank", "momentum_rank"}:
        raise ValueError("unsupported rank column")
    required = {"signal_date", "symbol", rank_column}
    missing = sorted(required - set(states.columns))
    if missing:
        raise ValueError(f"states missing columns: {missing}")
    targets: dict[str, dict[str, float]] = {}
    holdings: list[dict[str, object]] = []
    for date, group in states.groupby("signal_date", sort=True):
        selected = (
            group.sort_values([rank_column, "symbol"])
            .head(top_n)
        )
        if len(selected) != top_n:
            continue
        weight = 1.0 / top_n
        targets[str(date)] = {
            str(symbol): weight
            for symbol in selected["symbol"]
        }
        holdings.extend(
            {
                "signal_date": str(date),
                "symbol": str(row.symbol),
                "target_weight": weight,
                "rank": int(getattr(row, rank_column)),
                "return_5d": float(row.return_5d),
            }
            for row in selected.itertuples(index=False)
        )
    return targets, pd.DataFrame(holdings)
