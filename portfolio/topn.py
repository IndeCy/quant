"""通用 TopN 组合选择，不包含 Alpha 计算。"""

from __future__ import annotations

import pandas as pd


def select_topn(
    scored: pd.DataFrame,
    score_column: str,
    top_n: int,
) -> pd.DataFrame:
    """按分数降序、代码升序稳定选择 TopN。"""
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    missing = [column for column in ["symbol", score_column] if column not in scored.columns]
    if missing:
        raise ValueError(f"scored frame missing columns: {missing}")
    selected = scored.sort_values(
        [score_column, "symbol"],
        ascending=[False, True],
        kind="stable",
    ).head(top_n).copy()
    selected["rank"] = range(1, len(selected) + 1)
    return selected


def build_topn_selections(
    scored_by_date: pd.DataFrame,
    score_column: str,
    top_n: int,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """把月度横截面分数转换为选择名单和持仓明细。"""
    if "signal_date" not in scored_by_date.columns:
        raise ValueError("scored frame missing columns: ['signal_date']")
    selections: dict[str, list[str]] = {}
    holdings: list[pd.DataFrame] = []
    for signal_date, group in scored_by_date.groupby("signal_date", sort=True):
        selected = select_topn(group, score_column, top_n)
        selected["signal_date"] = str(signal_date)
        selections[str(signal_date)] = selected["symbol"].astype(str).tolist()
        holdings.append(selected)
    if not holdings:
        return selections, scored_by_date.iloc[0:0].copy()
    return selections, pd.concat(holdings, ignore_index=True)


def build_buffered_topn_selections(
    scored_by_date: pd.DataFrame,
    score_column: str,
    top_n: int,
    exit_rank: int,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """新标的进入TopN，旧持仓跌出退出排名后才替换。"""
    if exit_rank < top_n:
        raise ValueError("exit_rank must be greater than or equal to top_n")
    if "signal_date" not in scored_by_date.columns:
        raise ValueError("scored frame missing columns: ['signal_date']")
    previous: set[str] = set()
    selections: dict[str, list[str]] = {}
    holdings: list[pd.DataFrame] = []
    for signal_date, group in scored_by_date.groupby("signal_date", sort=True):
        ranked = select_topn(group, score_column, exit_rank)
        ranked_symbols = ranked["symbol"].astype(str).tolist()
        retained = previous.intersection(ranked_symbols)
        target = set(retained)
        for symbol in ranked_symbols:
            if len(target) >= top_n:
                break
            target.add(symbol)
        selected = ranked[ranked["symbol"].astype(str).isin(target)].copy()
        selected = selected.sort_values("rank", kind="stable").head(top_n)
        selected["signal_date"] = str(signal_date)
        chosen = selected["symbol"].astype(str).tolist()
        selections[str(signal_date)] = chosen
        previous = set(chosen)
        holdings.append(selected)
    if not holdings:
        return selections, scored_by_date.iloc[0:0].copy()
    return selections, pd.concat(holdings, ignore_index=True)
