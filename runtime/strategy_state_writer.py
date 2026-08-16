"""策略理论状态的统一持久化入口。"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from runtime.paths import RuntimePaths


@dataclass(frozen=True)
class StrategyHoldingState:
    """前端策略快照需要的最小持仓字段。"""

    symbol: str
    weight: float
    last_close: float


def write_strategy_instance_state(
    paths: RuntimePaths,
    strategy_id: str,
    trade_date: str,
    nav: float,
    holdings: list[StrategyHoldingState],
) -> None:
    """幂等保存理论净值和目标持仓，供策略页统一读取。"""
    with sqlite3.connect(paths.system_state_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_instance_state (
                strategy_id TEXT NOT NULL PRIMARY KEY,
                trade_date TEXT NOT NULL,
                nav REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_instance_holdings (
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                weight REAL NOT NULL,
                last_close REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(strategy_id, symbol)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO strategy_instance_state(strategy_id, trade_date, nav)
            VALUES (?, ?, ?)
            ON CONFLICT(strategy_id) DO UPDATE SET
                trade_date=excluded.trade_date,
                nav=excluded.nav,
                modified_at=CURRENT_TIMESTAMP
            """,
            [strategy_id, trade_date, nav],
        )
        connection.execute(
            "DELETE FROM strategy_instance_holdings WHERE strategy_id = ?",
            [strategy_id],
        )
        connection.executemany(
            """
            INSERT INTO strategy_instance_holdings(strategy_id, symbol, weight, last_close)
            VALUES (?, ?, ?, ?)
            """,
            [
                (strategy_id, item.symbol, item.weight, item.last_close)
                for item in holdings
            ],
        )
