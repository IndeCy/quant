"""
策略历史模块

用于持久化已经验证过的回测策略，支持按标的、时间区间、年度和策略名称分类查询。
默认写入 data/strategy_history.sqlite3，避免把本地研究历史提交到仓库。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_HISTORY_PATH = Path("data/strategy_history.sqlite3")


class StrategyHistoryStore:
    """已验证策略历史库。"""

    def __init__(self, db_path: Path | str = DEFAULT_HISTORY_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        """关闭 SQLite 连接。"""
        self.conn.close()

    def _init_schema(self) -> None:
        """初始化历史表结构。"""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_run_history (
              id integer PRIMARY KEY AUTOINCREMENT,
              symbol varchar(32) NOT NULL DEFAULT '',
              symbol_name varchar(100) NOT NULL DEFAULT '',
              strategy_name varchar(100) NOT NULL DEFAULT '',
              strategy_params mediumtext,
              start_date varchar(10) NOT NULL DEFAULT '',
              end_date varchar(10) NOT NULL DEFAULT '',
              provider varchar(50) NOT NULL DEFAULT '',
              benchmark_symbol varchar(32) NOT NULL DEFAULT '',
              benchmark_name varchar(100) NOT NULL DEFAULT '',
              metrics mediumtext,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS strategy_yearly_return_history (
              id integer PRIMARY KEY AUTOINCREMENT,
              run_id integer NOT NULL DEFAULT 0,
              symbol varchar(32) NOT NULL DEFAULT '',
              strategy_name varchar(100) NOT NULL DEFAULT '',
              year integer NOT NULL DEFAULT 0,
              strategy_return real NOT NULL DEFAULT 0,
              benchmark_return real NOT NULL DEFAULT 0,
              excess_return real NOT NULL DEFAULT 0,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_strategy_run_symbol
            ON strategy_run_history(symbol, strategy_name, start_date, end_date);

            CREATE INDEX IF NOT EXISTS idx_strategy_yearly_symbol
            ON strategy_yearly_return_history(symbol, strategy_name, year);
            """
        )
        self.conn.commit()

    def record_run(
        self,
        symbol: str,
        symbol_name: str,
        strategy_name: str,
        strategy_params: Dict[str, Any],
        start_date: str,
        end_date: str,
        provider: str,
        benchmark_symbol: str,
        benchmark_name: str,
        metrics: Dict[str, Any],
        yearly_returns: List[Dict[str, Any]],
    ) -> int:
        """记录一次已验证回测，并返回 run_id。"""
        cursor = self.conn.execute(
            """
            INSERT INTO strategy_run_history (
              symbol, symbol_name, strategy_name, strategy_params,
              start_date, end_date, provider, benchmark_symbol, benchmark_name, metrics
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                symbol_name,
                strategy_name,
                json.dumps(strategy_params, ensure_ascii=False, sort_keys=True),
                start_date,
                end_date,
                provider,
                benchmark_symbol,
                benchmark_name,
                json.dumps(metrics, ensure_ascii=False, sort_keys=True),
            ),
        )
        run_id = int(cursor.lastrowid)
        self.conn.executemany(
            """
            INSERT INTO strategy_yearly_return_history (
              run_id, symbol, strategy_name, year, strategy_return, benchmark_return, excess_return
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    symbol,
                    strategy_name,
                    int(row.get("year", 0)),
                    float(row.get("strategy_return", 0.0)),
                    float(row.get("benchmark_return", 0.0)),
                    float(row.get("excess_return", 0.0)),
                )
                for row in yearly_returns
            ],
        )
        self.conn.commit()
        return run_id

    def query_runs(
        self,
        symbol: Optional[str] = None,
        strategy_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按标的、策略和时间区间查询回测历史。"""
        conditions = []
        params: List[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if strategy_name:
            conditions.append("strategy_name = ?")
            params.append(strategy_name)
        if start_date:
            conditions.append("end_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("start_date <= ?")
            params.append(end_date)

        sql = "SELECT * FROM strategy_run_history"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY create_time DESC, id DESC"

        return [self._decode_run(dict(row)) for row in self.conn.execute(sql, params).fetchall()]

    def query_yearly_returns(
        self,
        symbol: Optional[str] = None,
        strategy_name: Optional[str] = None,
        year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """按标的、策略和年份查询年度收益历史。"""
        conditions = []
        params: List[Any] = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if strategy_name:
            conditions.append("strategy_name = ?")
            params.append(strategy_name)
        if year is not None:
            conditions.append("year = ?")
            params.append(year)

        sql = "SELECT * FROM strategy_yearly_return_history"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY year, run_id"

        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def classify_runs(self) -> Dict[str, Dict[Any, List[Dict[str, Any]]]]:
        """按标的、策略、年份三个维度分类历史记录。"""
        runs = self.query_runs()
        yearly_rows = self.query_yearly_returns()
        result: Dict[str, Dict[Any, List[Dict[str, Any]]]] = {
            "by_symbol": {},
            "by_strategy": {},
            "by_year": {},
        }

        for run in runs:
            result["by_symbol"].setdefault(run["symbol"], []).append(run)
            result["by_strategy"].setdefault(run["strategy_name"], []).append(run)

        for row in yearly_rows:
            result["by_year"].setdefault(row["year"], []).append(row)

        return result

    def _decode_run(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """解析 JSON 字段，返回业务友好的历史记录。"""
        row["strategy_params"] = json.loads(row.get("strategy_params") or "{}")
        row["metrics"] = json.loads(row.get("metrics") or "{}")
        return row
