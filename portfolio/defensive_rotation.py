"""正动量资产槽位与防守资产兜底的组合构建。"""

from __future__ import annotations

import pandas as pd


def build_defensive_rotation_targets(
    scores: pd.DataFrame,
    risky_symbols: list[str],
    defensive_symbol: str,
    *,
    top_n: int = 2,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame]:
    """正动量前 N 名占据等权槽位，空余槽位配置到防守资产。"""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    required = {"signal_date", "symbol", "factor_score"}
    missing = sorted(required - set(scores.columns))
    if missing:
        raise ValueError(f"scores missing columns: {missing}")
    allowed = set(risky_symbols)
    unknown = sorted(set(scores["symbol"].astype(str)) - allowed)
    if unknown:
        raise ValueError(f"scores contain unknown risky symbols: {unknown}")

    targets: dict[str, dict[str, float]] = {}
    holdings: list[dict[str, object]] = []
    slot_weight = 1.0 / top_n
    for signal_date, group in scores.groupby("signal_date", sort=True):
        positive = group[group["factor_score"].gt(0)].sort_values(
            ["factor_score", "symbol"],
            ascending=[False, True],
            kind="stable",
        )
        selected = positive.head(top_n)
        weights = {
            str(symbol): slot_weight
            for symbol in selected["symbol"].astype(str)
        }
        defensive_weight = 1.0 - sum(weights.values())
        if defensive_weight > 0:
            weights[defensive_symbol] = defensive_weight
        targets[str(signal_date)] = weights
        for rank, row in enumerate(selected.itertuples(index=False), start=1):
            holdings.append(
                {
                    "signal_date": str(signal_date),
                    "symbol": str(row.symbol),
                    "factor_score": float(row.factor_score),
                    "rank": rank,
                    "target_weight": slot_weight,
                    "role": "risk_asset",
                }
            )
        if defensive_weight > 0:
            holdings.append(
                {
                    "signal_date": str(signal_date),
                    "symbol": defensive_symbol,
                    "factor_score": 0.0,
                    "rank": top_n + 1,
                    "target_weight": defensive_weight,
                    "role": "defensive_fill",
                }
            )
    return targets, pd.DataFrame(holdings)
