"""科技行业 ETF 相对强度组合构建。"""

from __future__ import annotations

import pandas as pd


def build_tech_rotation_targets(
    states: pd.DataFrame,
    *,
    defensive_symbol: str,
    top_n: int = 2,
    slot_weight: float = 0.40,
    defensive_base_weight: float = 0.20,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """选择趋势有效的强势ETF，未使用风险槽位全部回到国债。"""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if slot_weight <= 0 or defensive_base_weight < 0:
        raise ValueError("weights must be non-negative")
    if top_n * slot_weight + defensive_base_weight > 1.0 + 1e-12:
        raise ValueError("target weights exceed 100%")
    targets: dict[str, dict[str, float]] = {}
    holdings: list[dict[str, object]] = []
    for signal_date, group in states.groupby("signal_date", sort=True):
        eligible = (
            group.loc[group["trend_active"].astype(bool)]
            .sort_values(["rank", "symbol"])
            .head(top_n)
        )
        weights = {
            str(row.symbol): slot_weight
            for row in eligible.itertuples(index=False)
        }
        defensive_weight = 1.0 - sum(weights.values())
        weights[defensive_symbol] = defensive_weight
        targets[str(signal_date)] = weights
        for symbol, weight in weights.items():
            holdings.append(
                {
                    "signal_date": str(signal_date),
                    "symbol": symbol,
                    "target_weight": float(weight),
                    "role": (
                        "DEFENSIVE"
                        if symbol == defensive_symbol
                        else "RELATIVE_STRENGTH"
                    ),
                }
            )
    return targets, pd.DataFrame(holdings)
