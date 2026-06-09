"""
模拟盘跟踪模块

用于记录真实模拟盘中的委托、成交、持仓和每日账户快照。
这类数据和回测历史分开存储，避免把未成交委托误认为历史回测结果。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_PAPER_TRADING_PATH = Path("data/paper_trading.sqlite3")


class PaperTradingStore:
    """模拟盘 SQLite 存储。"""

    def __init__(self, db_path: Path | str = DEFAULT_PAPER_TRADING_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        """关闭数据库连接。"""
        self.conn.close()

    def _init_schema(self) -> None:
        """初始化模拟盘账户、委托、持仓和快照表。"""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_account (
              id integer PRIMARY KEY AUTOINCREMENT,
              strategy_name varchar(100) NOT NULL DEFAULT '',
              strategy_code varchar(100) NOT NULL DEFAULT '',
              initial_cash real NOT NULL DEFAULT 0,
              cash real NOT NULL DEFAULT 0,
              benchmark_symbol varchar(32) NOT NULL DEFAULT '',
              benchmark_name varchar(100) NOT NULL DEFAULT '',
              start_date varchar(10) NOT NULL DEFAULT '',
              status varchar(20) NOT NULL DEFAULT 'ACTIVE',
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS paper_order (
              id integer PRIMARY KEY AUTOINCREMENT,
              account_id integer NOT NULL DEFAULT 0,
              order_date varchar(10) NOT NULL DEFAULT '',
              fill_date varchar(10) NOT NULL DEFAULT '',
              symbol varchar(32) NOT NULL DEFAULT '',
              symbol_name varchar(100) NOT NULL DEFAULT '',
              side varchar(10) NOT NULL DEFAULT '',
              price real NOT NULL DEFAULT 0,
              fill_price real NOT NULL DEFAULT 0,
              quantity integer NOT NULL DEFAULT 0,
              amount real NOT NULL DEFAULT 0,
              status varchar(20) NOT NULL DEFAULT 'PENDING',
              note varchar(255) NOT NULL DEFAULT '',
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS paper_position (
              id integer PRIMARY KEY AUTOINCREMENT,
              account_id integer NOT NULL DEFAULT 0,
              symbol varchar(32) NOT NULL DEFAULT '',
              symbol_name varchar(100) NOT NULL DEFAULT '',
              quantity integer NOT NULL DEFAULT 0,
              cost_amount real NOT NULL DEFAULT 0,
              avg_cost real NOT NULL DEFAULT 0,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(account_id, symbol)
            );

            CREATE TABLE IF NOT EXISTS paper_daily_snapshot (
              id integer PRIMARY KEY AUTOINCREMENT,
              account_id integer NOT NULL DEFAULT 0,
              trade_date varchar(10) NOT NULL DEFAULT '',
              total_value real NOT NULL DEFAULT 0,
              cash real NOT NULL DEFAULT 0,
              position_value real NOT NULL DEFAULT 0,
              strategy_return real NOT NULL DEFAULT 0,
              benchmark_return real NOT NULL DEFAULT 0,
              excess_return real NOT NULL DEFAULT 0,
              strongest_chain varchar(50) NOT NULL DEFAULT '',
              rebalance_signal varchar(20) NOT NULL DEFAULT '',
              target_symbols mediumtext,
              create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              modify_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(account_id, trade_date)
            );

            CREATE INDEX IF NOT EXISTS idx_paper_order_account
            ON paper_order(account_id, status, order_date);

            CREATE INDEX IF NOT EXISTS idx_paper_snapshot_account
            ON paper_daily_snapshot(account_id, trade_date);
            """
        )
        self.conn.commit()

    def create_account(
        self,
        strategy_name: str,
        strategy_code: str,
        initial_cash: float,
        benchmark_symbol: str,
        benchmark_name: str,
        start_date: str,
    ) -> int:
        """创建模拟盘账户，初始现金等于初始资金。"""
        cursor = self.conn.execute(
            """
            INSERT INTO paper_account (
              strategy_name, strategy_code, initial_cash, cash,
              benchmark_symbol, benchmark_name, start_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_name,
                strategy_code,
                float(initial_cash),
                float(initial_cash),
                benchmark_symbol,
                benchmark_name,
                start_date,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def get_account(self, account_id: int) -> Dict[str, Any]:
        """读取账户信息。"""
        row = self.conn.execute(
            "SELECT * FROM paper_account WHERE id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"模拟账户不存在: {account_id}")
        return dict(row)

    def record_pending_order(
        self,
        account_id: int,
        order_date: str,
        symbol: str,
        symbol_name: str,
        side: str,
        price: float,
        quantity: int,
        note: str = "",
    ) -> int:
        """记录一笔尚未成交的模拟委托。"""
        amount = float(price) * int(quantity)
        cursor = self.conn.execute(
            """
            INSERT INTO paper_order (
              account_id, order_date, symbol, symbol_name, side,
              price, quantity, amount, status, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """,
            (
                account_id,
                order_date,
                symbol,
                symbol_name,
                side,
                float(price),
                int(quantity),
                amount,
                note,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def fill_order(self, order_id: int, fill_date: str, fill_price: Optional[float] = None) -> None:
        """将待成交委托标记为已成交，并同步更新现金与持仓。"""
        order = self.conn.execute(
            "SELECT * FROM paper_order WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order is None:
            raise ValueError(f"委托不存在: {order_id}")
        order_dict = dict(order)
        if order_dict["status"] != "PENDING":
            raise ValueError(f"仅支持成交待处理委托: {order_id}")

        price = float(fill_price if fill_price is not None else order_dict["price"])
        quantity = int(order_dict["quantity"])
        amount = price * quantity
        account_id = int(order_dict["account_id"])
        side = order_dict["side"]

        if side == "BUY":
            self._apply_buy(account_id, order_dict["symbol"], order_dict["symbol_name"], quantity, amount)
        else:
            self._apply_sell(account_id, order_dict["symbol"], quantity, amount)

        self.conn.execute(
            """
            UPDATE paper_order
            SET fill_date = ?, fill_price = ?, amount = ?, status = 'FILLED',
                modify_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (fill_date, price, amount, order_id),
        )
        self.conn.commit()

    def _apply_buy(self, account_id: int, symbol: str, symbol_name: str, quantity: int, amount: float) -> None:
        """买入成交后扣现金，并按加权成本更新持仓。"""
        account = self.get_account(account_id)
        if float(account["cash"]) < amount:
            raise ValueError("账户现金不足，无法成交买入委托")
        position = self._get_position(account_id, symbol)
        old_quantity = int(position["quantity"]) if position else 0
        old_cost = float(position["cost_amount"]) if position else 0.0
        new_quantity = old_quantity + quantity
        new_cost = old_cost + amount
        avg_cost = new_cost / new_quantity if new_quantity else 0.0

        self.conn.execute(
            "UPDATE paper_account SET cash = cash - ?, modify_time = CURRENT_TIMESTAMP WHERE id = ?",
            (amount, account_id),
        )
        self.conn.execute(
            """
            INSERT INTO paper_position (
              account_id, symbol, symbol_name, quantity, cost_amount, avg_cost
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, symbol)
            DO UPDATE SET
              quantity = excluded.quantity,
              cost_amount = excluded.cost_amount,
              avg_cost = excluded.avg_cost,
              modify_time = CURRENT_TIMESTAMP
            """,
            (account_id, symbol, symbol_name, new_quantity, new_cost, avg_cost),
        )

    def _apply_sell(self, account_id: int, symbol: str, quantity: int, amount: float) -> None:
        """卖出成交后加现金，并按比例减少持仓成本。"""
        position = self._get_position(account_id, symbol)
        if position is None or int(position["quantity"]) < quantity:
            raise ValueError("持仓不足，无法成交卖出委托")
        old_quantity = int(position["quantity"])
        old_cost = float(position["cost_amount"])
        new_quantity = old_quantity - quantity
        new_cost = old_cost * new_quantity / old_quantity if new_quantity else 0.0

        self.conn.execute(
            "UPDATE paper_account SET cash = cash + ?, modify_time = CURRENT_TIMESTAMP WHERE id = ?",
            (amount, account_id),
        )
        if new_quantity == 0:
            self.conn.execute(
                "DELETE FROM paper_position WHERE account_id = ? AND symbol = ?",
                (account_id, symbol),
            )
        else:
            self.conn.execute(
                """
                UPDATE paper_position
                SET quantity = ?, cost_amount = ?, avg_cost = ?, modify_time = CURRENT_TIMESTAMP
                WHERE account_id = ? AND symbol = ?
                """,
                (new_quantity, new_cost, new_cost / new_quantity, account_id, symbol),
            )

    def _get_position(self, account_id: int, symbol: str) -> Optional[sqlite3.Row]:
        """查询单只股票持仓。"""
        return self.conn.execute(
            "SELECT * FROM paper_position WHERE account_id = ? AND symbol = ?",
            (account_id, symbol),
        ).fetchone()

    def list_positions(self, account_id: int) -> List[Dict[str, Any]]:
        """列出当前持仓。"""
        rows = self.conn.execute(
            "SELECT * FROM paper_position WHERE account_id = ? ORDER BY symbol",
            (account_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_orders(self, account_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出委托记录，可按状态过滤。"""
        params: List[Any] = [account_id]
        sql = "SELECT * FROM paper_order WHERE account_id = ?"
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY order_date DESC, id DESC"
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def record_daily_snapshot(
        self,
        account_id: int,
        trade_date: str,
        total_value: float,
        cash: float,
        position_value: float,
        strategy_return: float,
        benchmark_return: float,
        excess_return: float,
        strongest_chain: str,
        rebalance_signal: str,
        target_symbols: List[str],
    ) -> None:
        """写入或更新某日模拟盘净值快照。"""
        self.conn.execute(
            """
            INSERT INTO paper_daily_snapshot (
              account_id, trade_date, total_value, cash, position_value,
              strategy_return, benchmark_return, excess_return,
              strongest_chain, rebalance_signal, target_symbols
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, trade_date)
            DO UPDATE SET
              total_value = excluded.total_value,
              cash = excluded.cash,
              position_value = excluded.position_value,
              strategy_return = excluded.strategy_return,
              benchmark_return = excluded.benchmark_return,
              excess_return = excluded.excess_return,
              strongest_chain = excluded.strongest_chain,
              rebalance_signal = excluded.rebalance_signal,
              target_symbols = excluded.target_symbols,
              modify_time = CURRENT_TIMESTAMP
            """,
            (
                account_id,
                trade_date,
                float(total_value),
                float(cash),
                float(position_value),
                float(strategy_return),
                float(benchmark_return),
                float(excess_return),
                strongest_chain,
                rebalance_signal,
                json.dumps(target_symbols, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def list_daily_snapshots(self, account_id: int) -> List[Dict[str, Any]]:
        """按日期列出账户净值快照。"""
        rows = self.conn.execute(
            "SELECT * FROM paper_daily_snapshot WHERE account_id = ? ORDER BY trade_date",
            (account_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["target_symbols"] = json.loads(item.get("target_symbols") or "[]")
            result.append(item)
        return result
