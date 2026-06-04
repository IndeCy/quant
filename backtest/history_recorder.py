"""
策略历史记录写入工具

用于把批量策略对比结果统一写入 StrategyHistoryStore，便于后续回溯。
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from backtest.history import StrategyHistoryStore


def _row_metrics(row: pd.Series) -> Dict[str, Any]:
    """将对比表单行转换为历史库 metrics 字段。"""
    ignored = {"策略", "策略类型"}
    return {
        key: (value.item() if hasattr(value, "item") else value)
        for key, value in row.items()
        if key not in ignored
    }


def record_comparison_results(
    store: StrategyHistoryStore,
    comparison: pd.DataFrame,
    symbol: str,
    symbol_name: str,
    start_date: str,
    end_date: str,
    provider: str,
    benchmark_symbol: str,
    benchmark_name: str,
    strategy_params: Dict[str, Any] | None = None,
) -> List[int]:
    """批量记录策略对比结果，并返回 run_id 列表。"""
    run_ids: List[int] = []
    for _, row in comparison.iterrows():
        params = dict(strategy_params or {})
        params["strategy_type"] = row.get("策略类型", "")
        run_id = store.record_run(
            symbol=symbol,
            symbol_name=symbol_name,
            strategy_name=str(row["策略"]),
            strategy_params=params,
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            benchmark_symbol=benchmark_symbol,
            benchmark_name=benchmark_name,
            metrics=_row_metrics(row),
            yearly_returns=[],
        )
        run_ids.append(run_id)
    return run_ids
