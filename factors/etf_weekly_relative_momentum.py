"""ETF 周频横截面相对动量。"""

from __future__ import annotations

import pandas as pd


def calculate_weekly_relative_momentum(
    adjusted_close: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    symbols: list[str],
    *,
    lookback_days: int = 20,
) -> pd.DataFrame:
    """只用信号日及以前价格计算固定窗口收益并从强到弱排名。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    normalized = list(dict.fromkeys(str(symbol) for symbol in symbols))
    missing = sorted(set(normalized) - set(adjusted_close.columns))
    if missing:
        raise ValueError(f"adjusted_close missing symbols: {missing}")
    close = adjusted_close[normalized].sort_index().astype(float)
    momentum = close / close.shift(lookback_days) - 1.0
    rows: list[dict[str, object]] = []
    for raw_date in signal_dates:
        date = pd.Timestamp(raw_date)
        if date not in momentum.index:
            continue
        daily = [
            {
                "signal_date": date.strftime("%Y%m%d"),
                "symbol": symbol,
                "momentum": float(momentum.at[date, symbol]),
            }
            for symbol in normalized
            if pd.notna(momentum.at[date, symbol])
        ]
        ranked = sorted(
            daily,
            key=lambda item: (-float(item["momentum"]), str(item["symbol"])),
        )
        for rank, item in enumerate(ranked, start=1):
            rows.append({**item, "rank": rank})
    return pd.DataFrame(rows)


def build_top_momentum_targets(
    states: pd.DataFrame,
    *,
    top_n: int,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """每期等权持有相对动量前N名。"""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    required = {"signal_date", "symbol", "momentum", "rank"}
    missing = sorted(required - set(states.columns))
    if missing:
        raise ValueError(f"states missing columns: {missing}")
    targets: dict[str, dict[str, float]] = {}
    rows: list[dict[str, object]] = []
    for date, group in states.groupby("signal_date", sort=True):
        selected = group.sort_values(["rank", "symbol"]).head(top_n)
        if len(selected) != top_n:
            continue
        weight = 1.0 / top_n
        targets[str(date)] = {
            str(symbol): weight
            for symbol in selected["symbol"]
        }
        rows.extend(
            {
                "signal_date": str(date),
                "symbol": str(row.symbol),
                "target_weight": weight,
                "rank": int(row.rank),
                "momentum": float(row.momentum),
            }
            for row in selected.itertuples(index=False)
        )
    return targets, pd.DataFrame(rows)
