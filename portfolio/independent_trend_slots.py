"""跨资产独立趋势槽位组合。"""

from __future__ import annotations

import pandas as pd


def build_independent_trend_slot_targets(
    states: pd.DataFrame,
    risky_symbols: list[str],
    defensive_symbol: str,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """每个风险资产固定一个槽位，趋势关闭时将该槽位转入国债。"""
    required = {"signal_date", "symbol", "trend_active", "ma60", "ma120"}
    missing = sorted(required - set(states.columns))
    if missing:
        raise ValueError(f"trend states missing columns: {missing}")
    allowed = set(risky_symbols)
    unknown = sorted(set(states["symbol"].astype(str)) - allowed)
    if unknown:
        raise ValueError(f"trend states contain unknown symbols: {unknown}")
    if not risky_symbols:
        raise ValueError("risky_symbols cannot be empty")

    slot_weight = 1.0 / len(risky_symbols)
    targets: dict[str, dict[str, float]] = {}
    holdings: list[dict[str, object]] = []
    for signal_date, group in states.groupby("signal_date", sort=True):
        if set(group["symbol"].astype(str)) != allowed:
            continue
        weights: dict[str, float] = {}
        defensive_weight = 0.0
        for row in group.sort_values("symbol").itertuples(index=False):
            if bool(row.trend_active):
                weights[str(row.symbol)] = slot_weight
                role = "active_risk_slot"
            else:
                defensive_weight += slot_weight
                role = "defensive_redirect"
            holdings.append(
                {
                    "signal_date": str(signal_date),
                    "symbol": str(row.symbol),
                    "trend_active": bool(row.trend_active),
                    "ma60": float(row.ma60),
                    "ma120": float(row.ma120),
                    "slot_weight": slot_weight,
                    "role": role,
                }
            )
        if defensive_weight > 0:
            weights[defensive_symbol] = defensive_weight
        targets[str(signal_date)] = weights
    return targets, pd.DataFrame(holdings)
