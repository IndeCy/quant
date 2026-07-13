"""策略 Paper 净值曲线合并工具。"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd


def attach_paper_nav(frame: pd.DataFrame, paper_path: Path, strategy_id: str) -> pd.DataFrame:
    """把模拟盘实际净值拼到策略理论曲线，保持策略曲线接口向后兼容。"""
    if frame.empty or not paper_path.exists():
        return frame
    paper = _load_paper_nav(paper_path, strategy_id)
    if paper.empty:
        return frame
    result = frame.copy()
    result["trade_date"] = result["trade_date"].astype(str)
    return result.merge(paper, on="trade_date", how="left")


def _load_paper_nav(paper_path: Path, strategy_id: str) -> pd.DataFrame:
    """读取指定策略的 Paper 账户快照，并按首个快照归一化。"""
    try:
        with sqlite3.connect(paper_path) as con:
            frame = pd.read_sql_query(
                """
                SELECT s.trade_date, s.total_value
                FROM paper_daily_snapshot s
                JOIN paper_account a ON a.id = s.account_id
                WHERE a.strategy_code = ?
                ORDER BY s.trade_date
                """,
                con,
                params=[strategy_id],
            )
    except sqlite3.Error:
        return pd.DataFrame()
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False)
    frame["total_value"] = pd.to_numeric(frame["total_value"], errors="coerce")
    frame = frame.dropna(subset=["total_value"])
    frame = frame[frame["total_value"] > 0]
    if frame.empty:
        return frame
    base_value = float(frame.iloc[0]["total_value"])
    if base_value <= 0:
        return pd.DataFrame()
    frame["paper_nav"] = frame["total_value"] / base_value
    return frame[["trade_date", "paper_nav"]]
