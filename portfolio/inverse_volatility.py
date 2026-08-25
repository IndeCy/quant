"""跨资产逆波动风险预算组合构建。"""

from __future__ import annotations

import math

import pandas as pd


def build_inverse_volatility_targets(
    adjusted_close: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    symbols: list[str],
    *,
    lookback_days: int = 60,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """用信号日及以前的固定窗口波动率生成月度目标权重。"""
    if lookback_days < 2:
        raise ValueError("lookback_days must be at least 2")
    normalized_symbols = list(dict.fromkeys(str(item) for item in symbols))
    missing = sorted(set(normalized_symbols) - set(adjusted_close.columns))
    if missing:
        raise ValueError(f"adjusted_close missing symbols: {missing}")

    close = adjusted_close[normalized_symbols].sort_index().astype(float)
    daily_returns = close.pct_change(fill_method=None)
    volatility = daily_returns.rolling(
        lookback_days,
        min_periods=lookback_days,
    ).std(ddof=1) * math.sqrt(252)
    targets: dict[str, dict[str, float]] = {}
    diagnostics: list[dict[str, object]] = []
    for raw_date in signal_dates:
        signal_date = pd.Timestamp(raw_date)
        if signal_date not in volatility.index:
            continue
        values = volatility.loc[signal_date]
        if values[normalized_symbols].isna().any():
            continue
        if values[normalized_symbols].le(0).any():
            continue
        inverse = {
            symbol: 1.0 / float(values[symbol])
            for symbol in normalized_symbols
        }
        total = sum(inverse.values())
        weights = {
            symbol: score / total
            for symbol, score in inverse.items()
        }
        date_key = signal_date.strftime("%Y%m%d")
        targets[date_key] = weights
        for symbol in normalized_symbols:
            diagnostics.append(
                {
                    "signal_date": date_key,
                    "symbol": symbol,
                    "volatility": float(values[symbol]),
                    "target_weight": weights[symbol],
                }
            )
    return targets, pd.DataFrame(diagnostics)
