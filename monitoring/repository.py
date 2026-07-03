"""监控指标 SQLite 仓库。"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd


class MonitoringRepository:
    """负责策略与大盘监控指标的幂等读写。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            self._init_schema(con)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def upsert_strategy_daily(self, frame: pd.DataFrame) -> None:
        """按 trade_date + strategy_id 覆盖写入策略日频指标。"""
        if frame.empty:
            return
        columns = [
            "trade_date",
            "strategy_id",
            "strategy_name",
            "nav",
            "daily_return",
            "cumulative_return",
            "benchmark_id",
            "benchmark_nav",
            "benchmark_return",
            "excess_return",
            "drawdown",
            "max_drawdown",
            "volatility_20",
            "volatility_60",
            "sharpe_rolling",
            "exposure",
            "turnover_notional",
            "total_execution_cost",
            "failed_order_count",
        ]
        data = frame.reindex(columns=columns).copy()
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO strategy_nav_daily(
                    trade_date, strategy_id, strategy_name, nav, daily_return,
                    cumulative_return, benchmark_id, benchmark_nav, benchmark_return,
                    excess_return, drawdown, max_drawdown, volatility_20,
                    volatility_60, sharpe_rolling, exposure, turnover_notional,
                    total_execution_cost, failed_order_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, strategy_id) DO UPDATE SET
                    strategy_name=excluded.strategy_name,
                    nav=excluded.nav,
                    daily_return=excluded.daily_return,
                    cumulative_return=excluded.cumulative_return,
                    benchmark_id=excluded.benchmark_id,
                    benchmark_nav=excluded.benchmark_nav,
                    benchmark_return=excluded.benchmark_return,
                    excess_return=excluded.excess_return,
                    drawdown=excluded.drawdown,
                    max_drawdown=excluded.max_drawdown,
                    volatility_20=excluded.volatility_20,
                    volatility_60=excluded.volatility_60,
                    sharpe_rolling=excluded.sharpe_rolling,
                    exposure=excluded.exposure,
                    turnover_notional=excluded.turnover_notional,
                    total_execution_cost=excluded.total_execution_cost,
                    failed_order_count=excluded.failed_order_count,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [tuple(row) for row in data.itertuples(index=False, name=None)],
            )

    def upsert_market_daily(self, frame: pd.DataFrame) -> None:
        """按 trade_date + benchmark_id 覆盖写入大盘日频指标。"""
        if frame.empty:
            return
        columns = [
            "trade_date",
            "benchmark_id",
            "benchmark_nav",
            "benchmark_return",
            "benchmark_drawdown",
            "ma60",
            "ma120",
            "trend_state",
            "breadth_up_count",
            "breadth_down_count",
            "limit_up_count",
            "limit_down_count",
        ]
        data = frame.reindex(columns=columns).copy()
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO market_state_daily(
                    trade_date, benchmark_id, benchmark_nav, benchmark_return,
                    benchmark_drawdown, ma60, ma120, trend_state, breadth_up_count,
                    breadth_down_count, limit_up_count, limit_down_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, benchmark_id) DO UPDATE SET
                    benchmark_nav=excluded.benchmark_nav,
                    benchmark_return=excluded.benchmark_return,
                    benchmark_drawdown=excluded.benchmark_drawdown,
                    ma60=excluded.ma60,
                    ma120=excluded.ma120,
                    trend_state=excluded.trend_state,
                    breadth_up_count=excluded.breadth_up_count,
                    breadth_down_count=excluded.breadth_down_count,
                    limit_up_count=excluded.limit_up_count,
                    limit_down_count=excluded.limit_down_count,
                    modified_at=CURRENT_TIMESTAMP
                """,
                [tuple(row) for row in data.itertuples(index=False, name=None)],
            )

    def load_strategy_history(self, strategy_id: str) -> pd.DataFrame:
        """读取某策略完整观测历史。"""
        with self._connect() as con:
            return pd.read_sql_query(
                "SELECT * FROM strategy_nav_daily WHERE strategy_id = ? ORDER BY trade_date",
                con,
                params=[strategy_id],
            )

    def delete_strategy_history(self, strategy_id: str) -> None:
        """删除废弃策略的监控曲线，避免看板继续展示旧口径。"""
        with self._connect() as con:
            con.execute("DELETE FROM strategy_nav_daily WHERE strategy_id = ?", [strategy_id])

    def load_market_history(self, benchmark_id: str) -> pd.DataFrame:
        """读取某基准完整大盘观测历史。"""
        with self._connect() as con:
            return pd.read_sql_query(
                "SELECT * FROM market_state_daily WHERE benchmark_id = ? ORDER BY trade_date",
                con,
                params=[benchmark_id],
            )

    def load_latest_strategy_metrics(self, strategy_id: str) -> dict[str, object] | None:
        """读取策略最新一日指标。"""
        history = self.load_strategy_history(strategy_id)
        if history.empty:
            return None
        return dict(history.iloc[-1])

    def _init_schema(self, con: sqlite3.Connection) -> None:
        """初始化轻量监控表。"""
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_nav_daily (
                trade_date TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                nav REAL NOT NULL,
                daily_return REAL NOT NULL,
                cumulative_return REAL NOT NULL,
                benchmark_id TEXT NOT NULL,
                benchmark_nav REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                excess_return REAL NOT NULL,
                drawdown REAL NOT NULL,
                max_drawdown REAL NOT NULL,
                volatility_20 REAL NOT NULL,
                volatility_60 REAL NOT NULL,
                sharpe_rolling REAL NOT NULL,
                exposure REAL NOT NULL,
                turnover_notional REAL NOT NULL,
                total_execution_cost REAL NOT NULL,
                failed_order_count INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, strategy_id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS market_state_daily (
                trade_date TEXT NOT NULL,
                benchmark_id TEXT NOT NULL,
                benchmark_nav REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                benchmark_drawdown REAL NOT NULL,
                ma60 REAL NOT NULL,
                ma120 REAL NOT NULL,
                trend_state TEXT NOT NULL,
                breadth_up_count INTEGER NOT NULL DEFAULT 0,
                breadth_down_count INTEGER NOT NULL DEFAULT 0,
                limit_up_count INTEGER NOT NULL DEFAULT 0,
                limit_down_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, benchmark_id)
            )
            """
        )
