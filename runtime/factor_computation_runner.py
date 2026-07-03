"""因子计算 Runner。"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Protocol

import pandas as pd

from runtime.paths import RuntimePaths, get_runtime_paths
from runtime.repository import SystemRepository


class FactorComputationError(RuntimeError):
    """因子计算失败。"""


class FactorCalculator(Protocol):
    """因子计算器协议。"""

    def compute(self, contract: dict[str, Any], trade_date: str) -> pd.DataFrame:
        """返回包含 symbol、value 的因子分数表。"""


def run_factor_computation(
    paths: RuntimePaths | None,
    factor_id: str,
    trade_date: str,
    calculator: FactorCalculator,
) -> dict[str, Any]:
    """根据因子契约运行计算器，并幂等写入标准分数库。"""
    runtime_paths = paths or get_runtime_paths()
    runtime_paths.ensure_directories()
    repository = SystemRepository(runtime_paths.system_state_path)
    contract = repository.load_factor_contract(factor_id)
    if contract is None:
        raise FactorComputationError(f"factor contract not found: {factor_id}")

    frame = calculator.compute(contract, trade_date)
    normalized = _normalize_scores(frame, factor_id, trade_date)
    _write_scores(runtime_paths.factor_scores_path, normalized)
    return {
        "factor_id": factor_id,
        "trade_date": trade_date,
        "status": "SUCCESS",
        "written_count": len(normalized),
        "path": str(runtime_paths.factor_scores_path),
    }


def _normalize_scores(frame: pd.DataFrame, factor_id: str, trade_date: str) -> pd.DataFrame:
    """校验并统一计算结果字段。"""
    missing = [column for column in ["symbol", "value"] if column not in frame.columns]
    if missing:
        raise FactorComputationError(f"missing required columns: {missing}")
    result = frame.copy()
    result["trade_date"] = trade_date
    result["factor_id"] = factor_id
    result = result[["trade_date", "symbol", "factor_id", "value", *([ "close" ] if "close" in result.columns else [])]]
    result["symbol"] = result["symbol"].astype(str)
    result["value"] = result["value"].astype(float)
    if "close" in result.columns:
        result["close"] = result["close"].astype(float)
    return result.drop_duplicates(["trade_date", "symbol", "factor_id"], keep="last")


def _write_scores(path: Path, frame: pd.DataFrame) -> None:
    """幂等写入 factor_scores，并同步可选价格。"""
    with sqlite3.connect(path) as con:
        _init_schema(con)
        trade_dates = sorted(set(frame["trade_date"].astype(str)))
        factor_ids = sorted(set(frame["factor_id"].astype(str)))
        for trade_date in trade_dates:
            for factor_id in factor_ids:
                con.execute(
                    "DELETE FROM factor_scores WHERE trade_date = ? AND factor_id = ?",
                    [trade_date, factor_id],
                )
        con.executemany(
            """
            INSERT INTO factor_scores(trade_date, symbol, factor_id, value)
            VALUES (?, ?, ?, ?)
            """,
            [
                (row.trade_date, row.symbol, row.factor_id, float(row.value))
                for row in frame[["trade_date", "symbol", "factor_id", "value"]].itertuples(index=False)
            ],
        )
        if "close" in frame.columns:
            for trade_date in trade_dates:
                con.execute("DELETE FROM daily_prices WHERE trade_date = ?", [trade_date])
            con.executemany(
                """
                INSERT INTO daily_prices(trade_date, symbol, close)
                VALUES (?, ?, ?)
                """,
                [
                    (row.trade_date, row.symbol, float(row.close))
                    for row in frame[["trade_date", "symbol", "close"]].itertuples(index=False)
                ],
            )


def _init_schema(con: sqlite3.Connection) -> None:
    """初始化标准因子分数库。"""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_scores (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            factor_id TEXT NOT NULL,
            value REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, symbol, factor_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_prices (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            close REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, symbol)
        )
        """
    )
