"""本地Paper账户级执行参数持久化与版本迁移。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from backtest.paper_execution import (
    BrokerConfig,
    BrokerSimulator,
    OrderManager,
    PaperOrder,
)


MIGRATION_DIR = Path(__file__).with_name("paper_migrations")


def broker_config_from_instance(instance: dict[str, Any]) -> BrokerConfig | None:
    """仅显式声明时创建账户执行政策，旧策略继续沿用原有口径。"""
    config = instance.get("config") if isinstance(instance.get("config"), dict) else {}
    payload = config.get("paper_execution_policy")
    if not isinstance(payload, dict):
        return None
    return BrokerConfig(
        slippage_bps=float(payload.get("slippage_bps", 5.0)),
        execution_delay=int(payload.get("execution_delay", 1)),
        max_participation_rate=float(payload.get("max_participation_rate", 0.20)),
        commission_rate=float(payload.get("commission_rate", 0.0)),
        stamp_tax_rate=float(payload.get("stamp_tax_rate", 0.0)),
        min_commission=float(payload.get("min_commission", 0.0)),
        lot_size=int(payload.get("lot_size", 1)),
        open_aware_order_sizing=bool(
            payload.get("open_aware_order_sizing", False)
        ),
        tax_exempt_symbols=frozenset(
            str(symbol) for symbol in payload.get("tax_exempt_symbols", [])
        ),
    )


class PaperExecutionPolicyManager:
    """为每个Paper账户绑定独立成交口径，未绑定账户保持旧默认值。"""

    def __init__(
        self,
        db_path: str | Path,
        explicit_config: BrokerConfig | None,
    ) -> None:
        self.db_path = Path(db_path)
        self.explicit_config = explicit_config
        self.default_broker = BrokerSimulator(explicit_config or BrokerConfig())
        self._brokers: dict[int, BrokerSimulator] = {}
        apply_paper_migrations(self.db_path)

    def bind_account(self, account_id: int) -> None:
        """仅在调用方显式传入参数时落库，避免改写旧账户语义。"""
        if self.explicit_config is None:
            return
        save_execution_policy(
            self.db_path,
            account_id,
            self.explicit_config,
        )
        self._brokers[account_id] = BrokerSimulator(self.explicit_config)

    def load(self, account_id: int) -> BrokerConfig | None:
        """读取账户执行参数，缺失表示继续使用历史默认口径。"""
        return load_execution_policy(self.db_path, account_id)

    def execute(
        self,
        account_id: int,
        order: PaperOrder,
        market_row: pd.Series,
        manager: OrderManager,
    ) -> PaperOrder:
        """按账户选择模拟券商，开盘批量撮合时互不串用参数。"""
        broker = self._brokers.get(account_id)
        if broker is None:
            config = self.load(account_id)
            broker = BrokerSimulator(config) if config is not None else self.default_broker
            self._brokers[account_id] = broker
        return broker.execute(order, market_row, manager)


def apply_paper_migrations(db_path: str | Path) -> None:
    """按文件名顺序执行一次性SQLite迁移。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_schema_migration (
              version varchar(100) PRIMARY KEY,
              applied_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            str(row[0])
            for row in connection.execute(
                "SELECT version FROM paper_schema_migration"
            ).fetchall()
        }
        for migration in sorted(MIGRATION_DIR.glob("*.sql")):
            if migration.name in applied:
                continue
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO paper_schema_migration (version) VALUES (?)",
                (migration.name,),
            )
        connection.commit()


def save_execution_policy(
    db_path: str | Path,
    account_id: int,
    config: BrokerConfig,
) -> None:
    """幂等保存账户成交参数，税费豁免标的使用稳定JSON。"""
    payload = json.dumps(
        sorted(config.tax_exempt_symbols),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO paper_execution_policy (
              account_id, slippage_bps, execution_delay, max_participation_rate,
              commission_rate, stamp_tax_rate, min_commission, lot_size,
              tax_exempt_symbols, open_aware_order_sizing
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
              slippage_bps = excluded.slippage_bps,
              execution_delay = excluded.execution_delay,
              max_participation_rate = excluded.max_participation_rate,
              commission_rate = excluded.commission_rate,
              stamp_tax_rate = excluded.stamp_tax_rate,
              min_commission = excluded.min_commission,
              lot_size = excluded.lot_size,
              tax_exempt_symbols = excluded.tax_exempt_symbols,
              open_aware_order_sizing = excluded.open_aware_order_sizing,
              modify_time = CURRENT_TIMESTAMP
            """,
            (
                int(account_id),
                float(config.slippage_bps),
                int(config.execution_delay),
                float(config.max_participation_rate),
                float(config.commission_rate),
                float(config.stamp_tax_rate),
                float(config.min_commission),
                int(config.lot_size),
                payload,
                int(config.open_aware_order_sizing),
            ),
        )
        connection.commit()


def load_execution_policy(
    db_path: str | Path,
    account_id: int,
) -> BrokerConfig | None:
    """把数据库记录还原为BrokerConfig。"""
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM paper_execution_policy WHERE account_id = ?",
            (int(account_id),),
        ).fetchone()
    if row is None:
        return None
    return BrokerConfig(
        slippage_bps=float(row["slippage_bps"]),
        execution_delay=int(row["execution_delay"]),
        max_participation_rate=float(row["max_participation_rate"]),
        commission_rate=float(row["commission_rate"]),
        stamp_tax_rate=float(row["stamp_tax_rate"]),
        min_commission=float(row["min_commission"]),
        lot_size=int(row["lot_size"]),
        open_aware_order_sizing=bool(row["open_aware_order_sizing"]),
        tax_exempt_symbols=frozenset(
            str(item)
            for item in json.loads(str(row["tax_exempt_symbols"] or "[]"))
        ),
    )
