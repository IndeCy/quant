"""把 Paper Broker 事实账本投影为统一账户查询模型。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from runtime.local_paper_broker import LocalPaperBroker
from runtime.paths import RuntimePaths
from runtime.portfolio_account import build_account_snapshot
from runtime.repository import SystemRepository


def project_paper_account_snapshot(
    paths: RuntimePaths,
    broker: LocalPaperBroker,
    account_id: int,
    trade_date: str,
    market_data: pd.DataFrame,
    target_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """从成交账本重建账户快照，前端状态不得自行拼接持仓。"""
    account = broker.store.get_account(account_id)
    strategy_id = str(account["strategy_code"])
    repository = SystemRepository(paths.system_state_path)
    weights = target_weights if target_weights is not None else _latest_target_weights(repository, strategy_id)
    prices = _market_prices(market_data, trade_date)
    actual_positions: dict[str, dict[str, Any]] = {}
    for position in broker.store.list_positions(account_id):
        symbol = str(position["symbol"])
        last_price = prices.get(symbol, float(position.get("avg_cost") or 0.0))
        quantity = int(position.get("quantity") or 0)
        actual_positions[symbol] = {
            "market_value": quantity * last_price,
            "quantity": quantity,
            "last_close": last_price,
        }
    cash = float(account["cash"])
    total_value = cash + sum(float(item["market_value"]) for item in actual_positions.values())
    snapshot = build_account_snapshot(
        strategy_id=strategy_id,
        trade_date=_compact_date(trade_date),
        total_value=total_value,
        cash=cash,
        target_weights=weights,
        actual_positions=actual_positions,
    )
    repository.upsert_account_snapshot(snapshot)
    return snapshot


def _latest_target_weights(repository: SystemRepository, strategy_id: str) -> dict[str, float]:
    """沿用最近目标组合，开盘成交只改变实际仓位而不改变策略目标。"""
    previous = repository.load_account_snapshot(strategy_id)
    if previous is None:
        return {}
    return {
        str(position["symbol"]): float(position.get("target_weight") or 0.0)
        for position in previous.get("positions", [])
        if float(position.get("target_weight") or 0.0) > 0
    }


def _market_prices(market_data: pd.DataFrame, trade_date: str) -> dict[str, float]:
    """提取指定交易日最新价格，缺失标的由账本成本价保守估值。"""
    if market_data.empty:
        return {}
    frame = market_data.copy()
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    frame = frame[frame["trade_date"].eq(_compact_date(trade_date))]
    return {
        str(row["symbol"]): float(row["close"])
        for _, row in frame.iterrows()
        if float(row.get("close") or 0.0) > 0
    }


def _compact_date(value: str) -> str:
    text = str(value).replace("-", "")[:8]
    if len(text) != 8:
        raise ValueError(f"非法交易日: {value}")
    return text
