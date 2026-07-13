"""监控指标 SQLite 仓库。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pandas as pd


class MonitoringRepository:
    """负责策略与大盘监控指标的幂等读写。"""

    MARKET_EXTRA_COLUMNS: dict[str, str] = {
        "breadth_flat_count": "INTEGER NOT NULL DEFAULT 0",
        "equal_weight_return": "REAL NOT NULL DEFAULT 0",
        "median_return": "REAL NOT NULL DEFAULT 0",
        "ma20_above_ratio": "REAL NOT NULL DEFAULT 0",
        "ma60_above_ratio": "REAL NOT NULL DEFAULT 0",
        "ma120_above_ratio": "REAL NOT NULL DEFAULT 0",
        "new_high_20_count": "INTEGER NOT NULL DEFAULT 0",
        "new_low_20_count": "INTEGER NOT NULL DEFAULT 0",
        "market_amount": "REAL NOT NULL DEFAULT 0",
        "amount_ma20": "REAL NOT NULL DEFAULT 0",
        "amount_ratio_20": "REAL NOT NULL DEFAULT 0",
        "low_amount_ratio": "REAL NOT NULL DEFAULT 0",
        "zero_volume_ratio": "REAL NOT NULL DEFAULT 0",
    }

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
            "breadth_flat_count",
            "equal_weight_return",
            "median_return",
            "ma20_above_ratio",
            "ma60_above_ratio",
            "ma120_above_ratio",
            "new_high_20_count",
            "new_low_20_count",
            "market_amount",
            "amount_ma20",
            "amount_ratio_20",
            "low_amount_ratio",
            "zero_volume_ratio",
        ]
        data = frame.reindex(columns=columns).copy()
        data = data.fillna(
            {
                "trend_state": "",
                "breadth_up_count": 0,
                "breadth_down_count": 0,
                "limit_up_count": 0,
                "limit_down_count": 0,
                **{name: 0 for name in self.MARKET_EXTRA_COLUMNS},
            }
        )
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO market_state_daily(
                    trade_date, benchmark_id, benchmark_nav, benchmark_return,
                    benchmark_drawdown, ma60, ma120, trend_state, breadth_up_count,
                    breadth_down_count, limit_up_count, limit_down_count,
                    breadth_flat_count, equal_weight_return, median_return,
                    ma20_above_ratio, ma60_above_ratio, ma120_above_ratio,
                    new_high_20_count, new_low_20_count, market_amount,
                    amount_ma20, amount_ratio_20, low_amount_ratio, zero_volume_ratio
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    breadth_flat_count=excluded.breadth_flat_count,
                    equal_weight_return=excluded.equal_weight_return,
                    median_return=excluded.median_return,
                    ma20_above_ratio=excluded.ma20_above_ratio,
                    ma60_above_ratio=excluded.ma60_above_ratio,
                    ma120_above_ratio=excluded.ma120_above_ratio,
                    new_high_20_count=excluded.new_high_20_count,
                    new_low_20_count=excluded.new_low_20_count,
                    market_amount=excluded.market_amount,
                    amount_ma20=excluded.amount_ma20,
                    amount_ratio_20=excluded.amount_ratio_20,
                    low_amount_ratio=excluded.low_amount_ratio,
                    zero_volume_ratio=excluded.zero_volume_ratio,
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

    def upsert_market_beta(self, snapshot: dict[str, object]) -> None:
        """按交易日覆盖写入统一 beta 观测快照。"""
        reasons = snapshot.get("reasons", [])
        reasons_json = json.dumps(reasons if isinstance(reasons, list) else [], ensure_ascii=False)
        values = (
            str(snapshot["trade_date"]),
            str(snapshot["beta_state"]),
            float(snapshot["beta_score"]),
            float(snapshot["trend_score"]),
            float(snapshot["breadth_score"]),
            float(snapshot["sentiment_score"]),
            float(snapshot["liquidity_score"]),
            float(snapshot["funding_score"]),
            float(snapshot["valuation_score"]),
            str(snapshot["risk_level"]),
            reasons_json,
        )
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO market_beta_daily(
                    trade_date, beta_state, beta_score, trend_score, breadth_score,
                    sentiment_score, liquidity_score, funding_score, valuation_score,
                    risk_level, reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    beta_state=excluded.beta_state,
                    beta_score=excluded.beta_score,
                    trend_score=excluded.trend_score,
                    breadth_score=excluded.breadth_score,
                    sentiment_score=excluded.sentiment_score,
                    liquidity_score=excluded.liquidity_score,
                    funding_score=excluded.funding_score,
                    valuation_score=excluded.valuation_score,
                    risk_level=excluded.risk_level,
                    reasons_json=excluded.reasons_json,
                    modified_at=CURRENT_TIMESTAMP
                """,
                values,
            )

    def load_market_beta_history(self, limit: int | None = None) -> list[dict[str, object]]:
        """读取 beta 观测历史，最新限制由 API 层传入。"""
        sql = "SELECT * FROM market_beta_daily ORDER BY trade_date"
        params: list[int] = []
        if limit is not None:
            sql = "SELECT * FROM market_beta_daily ORDER BY trade_date DESC LIMIT ?"
            params.append(int(limit))
        with self._connect() as con:
            rows = [self._decode_beta_row(row) for row in con.execute(sql, params).fetchall()]
        return list(reversed(rows)) if limit is not None else rows

    def load_latest_market_beta(self) -> dict[str, object] | None:
        """读取最新 beta 观测快照。"""
        rows = self.load_market_beta_history(limit=1)
        return rows[-1] if rows else None

    def load_latest_strategy_metrics(self, strategy_id: str) -> dict[str, object] | None:
        """读取策略最新一日指标。"""
        history = self.load_strategy_history(strategy_id)
        if history.empty:
            return None
        return dict(history.iloc[-1])

    def _decode_beta_row(self, row: tuple[object, ...]) -> dict[str, object]:
        """把 SQLite 行转换为 API 友好的 beta 记录。"""
        columns = [
            "trade_date",
            "beta_state",
            "beta_score",
            "trend_score",
            "breadth_score",
            "sentiment_score",
            "liquidity_score",
            "funding_score",
            "valuation_score",
            "risk_level",
            "reasons_json",
            "created_at",
            "modified_at",
        ]
        item = dict(zip(columns, row))
        item["reasons"] = json.loads(str(item.pop("reasons_json") or "[]"))
        return item

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
        self._migrate_market_state_daily(con)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS market_beta_daily (
                trade_date TEXT NOT NULL PRIMARY KEY,
                beta_state TEXT NOT NULL,
                beta_score REAL NOT NULL,
                trend_score REAL NOT NULL,
                breadth_score REAL NOT NULL,
                sentiment_score REAL NOT NULL,
                liquidity_score REAL NOT NULL,
                funding_score REAL NOT NULL,
                valuation_score REAL NOT NULL,
                risk_level TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _migrate_market_state_daily(self, con: sqlite3.Connection) -> None:
        """向后兼容补齐大盘观测派生字段，保留已有监控库数据。"""
        existing = {
            str(row[1])
            for row in con.execute("PRAGMA table_info(market_state_daily)").fetchall()
        }
        for column, definition in self.MARKET_EXTRA_COLUMNS.items():
            if column not in existing:
                con.execute(f"ALTER TABLE market_state_daily ADD COLUMN {column} {definition}")
